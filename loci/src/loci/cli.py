"""Loci command line.

    loci init-db
    loci check-sources [--urls]
    loci poi-snapshot [--month YYYY-MM] [--dry-run] [--force]
                                                        (the first-seen ledger:
                                                         analysis.poi_presence, one row
                                                         per deduped location per its
                                                         first/last observed month.
                                                         Run after every dedup, BEFORE
                                                         `loci chains detect`.)
    loci check-presence                                 (100% of deduped locations have
                                                         a ledger row; skips with no DB)
    loci check-questions
    loci check-tickets [--hook]
    loci reach-table [--quantile 0.80] [--write]        (read-only unless --write)
    loci spacing                                        (read-only)
    loci conveniences [--borough MN]                    (read-only, D58: queries
                                                        analysis.address_category)
    loci street-frame [--borough MNBK|MN|BK] [--spacing-m 100] [--refresh] [--dry-run]
                                                        (D84: the STREET sampling frame --
                                                         one point every 100 m along every
                                                         known CSCL street. Writes
                                                         data/interim/street_points.parquet;
                                                         run BEFORE address-gaps, which
                                                         consumes it.)
    loci address-gaps [--borough MNBK|MN|BK] [--reach tiers|p80] [--supply-set principled]
                      [--limit 0] [--street-frame/--no-street-frame] [--dry-run]
                      [--allow-out-of-scope]
                                                        (D48/D78: the screen is
                                                        Manhattan+Brooklyn; any other
                                                        borough needs --allow-out-of-scope.
                                                        D84: scores the lot AND street
                                                        frames in one run.)
    loci address-demand [--borough MNBK|MN|BK|ALL] [--dry-run]  (D49 annotation, GTM-110)
    loci address-access [--boroughs MN,BK] [--months 3] [--complex-point] [--dry-run]
                                                       (transit_entries_400m + jobs_400m
                                                        beside homes_400m; UPDATE-only,
                                                        never a filter on the screen)
    loci transit-profile [--boroughs MN,BK] [--months 3] [--re-sweep] [--dry-run]
                                                       (subway entries per day type x
                                                        daypart at address grain; reuses
                                                        analysis.address_entrance so a
                                                        rebuild is SQL, not Dijkstra)
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
        # Wishlist entries carry `grain` (the vendor's word) rather than the
        # pipeline's `geography`, so fall back before printing a bare dash.
        geo = s.get("geography") or s.get("grain") or "-"
        table.add_row(s["id"], s["tier"], s["role"], str(geo), cost_s, s["status"])
    console.print(table)


@app.command(name="check-sources")
def check_sources(urls: bool = typer.Option(False, "--urls", help="Also check every URL resolves.")) -> None:
    """Validate the registry and assert it agrees with docs/CONTEXT.md."""
    errors = registry.validate(check_urls=urls)
    for e in errors:
        console.print(f"[red]FAIL[/] {e}")
    raise typer.Exit(1 if errors else 0)


@app.command(name="poi-snapshot")
def poi_snapshot(
    month: str = typer.Option(None, "--month", help="Snapshot month YYYY-MM; "
                                                    "default the current month."),
    dry_run: bool = typer.Option(False, "--dry-run",
                                 help="Compute and print; write nothing."),
    force: bool = typer.Option(False, "--force",
                               help="Allow a month older than the ledger's newest. "
                                    "Read sql/018 caveat 2 first."),
) -> None:
    """Record one month of observation for every deduplicated POI location.

    This is the FIRST-SEEN LEDGER (`analysis.poi_presence`): independent of
    whether any source publishes an open date, it records the month Loci first
    and last SAW each storefront. Run it after every ingest + `loci dedup`, and
    before `loci chains detect` -- `make chains-refresh` does exactly that.

    Idempotent: re-running a month never moves a `first_seen_month` and never
    double-counts `n_months_seen`. Backfill for the ledger's first month marks
    every undated location `backfill_censored`, which means "already existed,
    true opening date unknown" -- never "opened this month"."""
    from loci.model import poi_presence as pp

    con = pp.connect_write()
    try:
        result = pp.snapshot(con, month=month, dry_run=dry_run, force=force)
    except (ValueError, RuntimeError) as exc:
        console.print(f"[red]FAIL[/] {exc}")
        raise typer.Exit(1) from exc

    t = Table(title=f"poi-snapshot {result.month}"
                    + (" — DRY RUN, nothing written" if result.dry_run else ""))
    t.add_column("metric"); t.add_column("n", justify="right")
    t.add_row("deduped locations seen", f"{result.n_locations:,}")
    t.add_row("  carried by key match", f"{result.n_matched_hash:,}")
    t.add_row("  carried by name+40 m link", f"{result.n_matched_link:,}")
    t.add_row("  minted this month", f"{result.n_new:,}")
    t.add_row("ledger rows NOT seen this month", f"{result.n_gone:,}")
    t.add_row("ledger rows total", f"{result.n_rows_total:,}")
    for kind, n in sorted(result.kinds.items()):
        t.add_row(f"first_seen_kind = {kind}", f"{n:,}")
    if result.hash_collisions:
        t.add_row("[yellow]key collisions (kept apart)[/]",
                  f"{result.hash_collisions:,}")
    if result.upgraded:
        t.add_row("[green]censored rows a source finally dated[/]",
                  f"{result.upgraded:,}")
    console.print(t)

    if result.kinds.get("backfill_censored"):
        console.print("[yellow]NOTE[/] left-censored rows existed when the ledger "
                      "started. Their true opening date is UNKNOWN — never report "
                      "them as openings in the ledger's first month.")
    if not result.dry_run:
        errors, stats = pp.coverage_check(con)
        for e in errors:
            console.print(f"[red]FAIL[/] {e}")
        if errors:
            raise typer.Exit(1)
        console.print(f"[green]ok[/] ledger covers "
                      f"{stats['coverage_pct']:.2f}% of "
                      f"{stats['clusters']:,} deduped locations")


@app.command(name="check-presence")
def check_presence() -> None:
    """Assert the first-seen ledger covers every deduplicated location.

    The drift check for `analysis.poi_presence`: after an ingest, 100% of
    current `analysis.poi_dedup` clusters must have a ledger row in the newest
    snapshot month, no cluster may be claimed by two ledger rows, and the
    `first_seen_kind` invariants must hold. Skips (exit 0) on a clone with no
    warehouse, the way a fresh checkout has none."""
    import pathlib as _pl

    from loci.model import poi_presence as pp

    import os as _os

    target = _pl.Path(_os.environ.get("LOCI_DB") or locidb.DEFAULT_PATH)
    if not target.exists():
        console.print(f"[yellow]skip[/] no warehouse at {target} — nothing to check")
        raise typer.Exit(0)
    from loci.model.recommend import connect_read_only

    con = connect_read_only()
    errors, stats = pp.coverage_check(con)
    for e in errors:
        console.print(f"[red]FAIL[/] {e}")
    if not errors:
        console.print(
            f"[green]ok[/] {stats['ledger_rows']:,} ledger rows, "
            f"{stats['coverage_pct']:.2f}% of {stats['clusters']:,} deduped "
            f"locations covered in {stats['newest_month']}; kinds="
            + ", ".join(f"{k}={v:,}" for k, v in sorted(stats["kinds"].items())))
    # The key-migration surface (sql/035): rows re-keyed, merged, unmapped, and
    # the one integrity check coverage_check cannot make -- a ledger row still
    # carrying a key an APPLIED map moved away from means the apply half-landed.
    from loci.model.poi_key_migration import format_migration
    line, km_errors = format_migration(con)
    if line:
        console.print(f"[green]ok[/] {line}" if not km_errors else f"[yellow]{line}[/]")
    for e in km_errors:
        console.print(f"[red]FAIL[/] {e}")
    raise typer.Exit(1 if errors or km_errors else 0)


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


def _load_street_frame(boroughs: list[str], limit: int = 0):
    """`data/interim/street_points.parquet` shaped like a lot frame, or None
    when `loci street-frame` has not run.

    The street frame arrives with the SAME column contract the PLUTO loader
    produces -- address_id, bbl, lon, lat, units, borough -- plus `frame` and
    the four street descriptors. `units` is 0 and not NULL on purpose: every
    catchment sum downstream is `COALESCE(units, 0)`, and a 0 contributes
    EXACTLY nothing to another row's homes_400m, which is what makes the D84
    non-filtering proof arithmetic rather than approximate. `bbl` is NULL, so
    every BBL join (PLUTO character, demographics, the laundry evidence views)
    drops street rows by construction.
    """
    import pandas as pd

    from loci.model import address_gaps as ag
    from loci.sources.cities.nyc import street_centerline as sc

    path = sc.POINTS_PARQUET
    if not path.exists():
        return None
    df = pd.read_parquet(path)
    df = df[df["borough"].isin(boroughs)].reset_index(drop=True)
    if df.empty:
        return None
    if limit:
        df = (df.groupby("borough", group_keys=False).head(limit).reset_index(drop=True))
    out = pd.DataFrame({
        "address_id": df["point_id"],
        "bbl": None,
        "lon": df["lon"],
        "lat": df["lat"],
        "units": 0.0,
        "address": df["street_name"],
        "borough": df["borough"],
        "frame": ag.STREET_FRAME,
        "frontage_m": df["frontage_m"],
        "street_name": df["street_name"],
        "frame_source": sc.SOURCE_ID,
        # Carried IN the parquet, not inferred from its mtime: a file copied
        # between machines keeps its extract date, and "how old is this frame"
        # must survive a `cp`.
        "frame_vintage": pd.to_datetime(df["frame_vintage"]).dt.date,
    })
    return out


@app.command(name="street-frame")
def street_frame_cmd(
    borough: str = typer.Option("MNBK", help="MNBK (default, the D78 screen scope) | MN | BK."),
    spacing_m: float = typer.Option(100.0, "--spacing-m",
                                    help="Metres between street points (L). 100 m is the "
                                         "D84 choice: the smallest round value at or above "
                                         "the MN+BK median block face (81.9 m), so one point "
                                         "stands for at most one block face."),
    refresh: bool = typer.Option(False, "--refresh",
                                 help="Re-fetch CSCL from the portal instead of reading "
                                      "the cached extract under data/raw/nyc_cscl/."),
    dry_run: bool = typer.Option(False, "--dry-run",
                                 help="Fetch, filter and print the ladder; write no parquet."),
) -> None:
    """Build the STREET sampling frame (D84): one scored point every `L` metres
    along every known street in scope.

    THE OWNER'S DIRECTION (2026-09-13): "for addresses, we should be sampling an
    address near the middle of every known street in the borough." The screen's
    frame was the residential tax lot (D38) -- built FROM RESIDENTS, so a street
    nobody lives on yet was not low-scoring, it was ABSENT. 9.3% of street
    points have no residential lot within 100 m, and they are a different
    population: median gap_score 2.07 against the lot frame's 1.27, three times
    the missing categories, half of them led by laundry.

    Writes `data/interim/street_points.parquet` and NOTHING ELSE. It does not
    touch the warehouse on purpose: `loci address-gaps` does
    `DELETE FROM analysis.address WHERE borough = ?` and would drop any street
    rows written here, so `address-gaps` CONSUMES this parquet and writes both
    frames in one delete-then-insert, under one provenance stamp, with neither
    frame able to end up a run ahead of the other (docs/street_midpoint_frame.md
    section 5). Run this BEFORE `loci address-gaps`.

    The keep rule (verified live 2026-09-13): status='2' AND rw_type=1 AND
    nonped<>'V' AND at grade -- 32,291 of 41,784 MN+BK segments, 3,476.8 km. The
    ladder is printed on every build so the filter is auditable rather than
    asserted, and the build REFUSES if the kept count has moved more than 10%
    from the verified baseline (CSCL refreshes weekly; drift is expected, a
    factor is not).
    """
    from loci.sources.cities.nyc import street_centerline as sc
    from loci.sources.cities.nyc.addresses import BOROCODE, SCREEN_BOROUGHS

    b = borough.upper()
    if b in ("MNBK", "DEFAULT"):
        boros = tuple(SCREEN_BOROUGHS)
    else:
        boros = tuple(x.strip() for x in b.split(",") if x.strip())
        bad = [x for x in boros if x not in BOROCODE]
        if bad:
            raise typer.BadParameter(f"unknown borough(s) {bad}; expected MNBK or "
                                     f"one of {sorted(BOROCODE)}")

    console.print(f"[dim]CSCL {sc.DATASET} ({'+'.join(boros)}), L = {spacing_m:.0f} m; "
                  f"{'re-fetching' if refresh else 'cached extract if present'}…[/]")
    try:
        points, report = sc.build_frame(boros, spacing_m=spacing_m,
                                        use_cache=not refresh,
                                        log=lambda s: console.print(f"[dim]{s}[/]"))
    except sc.StreetFrameError as exc:
        console.print(f"[red]{exc}[/]")
        raise typer.Exit(1)

    console.print(f"[bold]{report['segments_kept']:,}[/] segments kept of "
                  f"{report['rows_fetched']:,} fetched "
                  f"({report['km_kept']:,.1f} km, {report['multipart_segments']:,} multipart) "
                  f"-> [bold]{report['points']:,}[/] points")
    for boro, n in sorted(report["points_by_borough"].items()):
        console.print(f"  {boro}  {n:>8,} points")
    console.print(f"[dim]length check: computed / segmentlength = "
                  f"{report['length_check_ratio']:.4f} (must be 1.00 ± 1%); "
                  f"frontage median {points['frontage_m'].median():.1f} m; "
                  f"vintage {report['frame_vintage']}[/]")

    if dry_run:
        console.print("[dim]--dry-run: nothing written.[/]")
        return
    out = sc.POINTS_PARQUET
    out.parent.mkdir(parents=True, exist_ok=True)
    points["frame_vintage"] = report["frame_vintage"]
    points.to_parquet(out, index=False)
    console.print(f"[green]ok[/] wrote {len(points):,} street points -> {out}")
    console.print("[dim]next: `uv run loci address-gaps` — it unions this frame in and "
                  "scores both frames in one run.[/]")


@app.command(name="address-gaps")
def address_gaps_cmd(
    borough: str = typer.Option("MNBK", help="MNBK (default, the D48/D78 screen scope) | MN | BK | "
                                            "a comma list | ALL (needs --allow-out-of-scope)."),
    reach: str = typer.Option("tiers", help="'tiers' (CHECKPOINT D41, default) or 'p80' (reach.yaml)."),
    supply_set: str = typer.Option(SUPPLY_DEFAULT, "--supply-set",
                                   help="Which POIs count as supply: all | principled | "
                                        "corroborated (D52, score/supply.py). Recorded in "
                                        "analysis.address_gaps.supply_set/supply_hash."),
    limit: int = typer.Option(0, help="Cap addresses per borough, for smoke runs (0 = all)."),
    street_frame: bool = typer.Option(
        True, "--street-frame/--no-street-frame",
        help="Score the STREET frame beside the lot frame (D84), reading "
             "data/interim/street_points.parquet (built by `loci street-frame`). "
             "--no-street-frame scores lots only, which is the pre-D84 screen and "
             "the way to reproduce a pre-D84 run."),
    rank_by: str = typer.Option("density", "--rank-by",
                                help="Order the cluster list by 'density' (owner ruling "
                                     "2026-09-13, default: the units_capped-weighted median "
                                     "of member density_400m, capped units as tiebreak) or "
                                     "'units' (the pre-ruling Sum(units_capped) order). "
                                     "'density' needs `loci supply-ratio` to have run."),
    dry_run: bool = typer.Option(False, "--dry-run", help="Compute and print the summary; write nothing."),
    allow_out_of_scope: bool = typer.Option(
        False, "--allow-out-of-scope",
        help="Permit boroughs outside the D48/D78 screen scope (MN+BK). Deliberate, "
             "documented runs only -- the screen tables are read as the deliverable, and "
             "an out-of-scope run puts rows in them that the owner has ruled out of scope. "
             "Also suppresses the prune that otherwise removes such rows."),
) -> None:
    """Address-level gap screen (CHECKPOINT D33/D38/D39/D41): a fixed 800m/
    >=12-of-15 walkability gate (reach-independent), then a CONTINUOUS
    max(nearest_m/reach_m) ranking per residential PLUTO lot, clustered by
    lead category and proximity. Supersedes the old 800m/80% rule entirely.
    Writes analysis.address_gaps unless --dry-run.

    SCOPE (D48, re-ruled as D78 2026-09-13): the screen is Manhattan and
    Brooklyn. `--borough ALL`, or any borough outside MN+BK, is REFUSED unless
    --allow-out-of-scope is passed; and a normal in-scope run prunes any
    out-of-scope rows a previous wider run left behind, so the screen tables
    hold MN+BK and nothing else. The data foundation underneath -- the raw
    sources, poi_dedup/poi_supply, the hex tables, analysis.address_demographics
    -- stays citywide and is untouched by this."""
    import pandas as pd

    from loci.model import address_gaps as ag
    from loci.sources.cities.nyc.addresses import (
        BOROCODE,
        SCREEN_BOROUGHS,
        load_residential_addresses,
    )

    b = borough.upper()
    if b in ("MNBK", "DEFAULT"):
        boros = list(SCREEN_BOROUGHS)
    elif b == "ALL":
        boros = sorted(BOROCODE)
    else:
        boros = [x.strip() for x in b.split(",") if x.strip()]
        bad = [x for x in boros if x not in BOROCODE]
        if bad:
            raise typer.BadParameter(
                f"unknown borough(s) {bad}; expected MNBK, ALL, or one of {sorted(BOROCODE)}")
    out_of_scope = [x for x in boros if x not in SCREEN_BOROUGHS]
    if out_of_scope and not allow_out_of_scope:
        raise typer.BadParameter(
            f"{','.join(out_of_scope)} is outside the screen scope "
            f"{'+'.join(SCREEN_BOROUGHS)} (CHECKPOINT D48, owner ruling D78: "
            f"\"we are still focused on Manhattan and Brooklyn\"). analysis.address and "
            f"analysis.address_category are the deliverable and hold MN+BK only; the data "
            f"foundation stays citywide. Pass --allow-out-of-scope if you really mean to "
            f"write out-of-scope rows into the screen tables.")

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
    addresses_df["frame"] = ag.LOT_FRAME
    n_lot = len(addresses_df)

    # D84: the STREET frame, unioned in here rather than written by its own
    # command, because write_address_gaps delete-then-inserts per BOROUGH and
    # would drop street rows written before it. One union -> one run -> one
    # provenance stamp, and the two frames can never be one run apart.
    n_street = 0
    if street_frame:
        street_df = _load_street_frame(boros, limit=limit)
        if street_df is None:
            console.print("[yellow]no street frame[/] "
                          "(data/interim/street_points.parquet is missing) — scoring the "
                          "LOT frame only. Run `uv run loci street-frame` first, or pass "
                          "--no-street-frame to say you meant lots only (D84).")
        else:
            n_street = len(street_df)
            addresses_df = pd.concat([addresses_df, street_df], ignore_index=True)

    console.print(f"[dim]{len(addresses_df):,} scored points (borough={b}): "
                  f"{n_lot:,} lot + {n_street:,} street; "
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
        if not allow_out_of_scope:
            # D78: the writer only delete-then-inserts the boroughs it was
            # handed, so a narrower run cannot clean up after a wider one.
            # Idempotent: a no-op on every run after the first.
            n_addr, n_cat = ag.prune_out_of_scope(con, SCREEN_BOROUGHS)
            if n_addr or n_cat:
                console.print(f"[yellow]pruned[/] {n_addr:,} address and {n_cat:,} "
                              f"address_category rows outside "
                              f"{'+'.join(SCREEN_BOROUGHS)} (D48/D78)")

    if rank_by not in ag.RANK_BY:
        raise typer.BadParameter(f"--rank-by must be one of {ag.RANK_BY}; got {rank_by!r}")
    # `density_400m` lives on analysis.address (model/supply_ratio.py owns it,
    # off the same 400 m sweep as homes_400m) and NOT on the screen's own
    # working frame -- the screen runs BEFORE supply-ratio in the canonical
    # order. Join it in for the ranking only; nothing here writes it back, and
    # nothing about the gap set depends on it.
    df = df.merge(
        con.execute(
            "SELECT address_id, borough, density_400m, walkshed_km2_400m "
            "FROM analysis.address"
        ).fetchdf(),
        on=["address_id", "borough"], how="left")
    summary = ag.summarize_gap_run(df, rank_by=rank_by)
    console.print(f"{summary['n_addresses']:,} scored points, {summary['n_units']:,.0f} units, "
                  f"borough={b}, reach={reach}")
    # D84: the two frames side by side, never pooled into one headline. A
    # street point has no residents; counting it as an address would inflate
    # every "N addresses have a gap" number by ~17% for free.
    if len(summary["by_frame"]) > 1:
        console.print("[bold]by sampling frame (D84):[/]")
        for fr, s in summary["by_frame"].items():
            console.print(
                f"  {fr:7} {s['n_addresses']:>8,} points  {s['n_units']:>10,.0f} units  "
                f"{s['n_gap_addresses']:>8,} with a gap  median gap_score "
                f"{s['median_gap_score']:.2f}  {s['n_clusters']:>5,} clusters  "
                f"{s['lead_censored']:>7,} censored leads")
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

    if summary["rank_by_fallback"]:
        console.print(f"[yellow]--rank-by density unavailable[/] "
                      f"({summary['rank_by_fallback']}); listing by capped units instead")
    label = ("walk-shed density (units/km², units_capped-weighted median; capped units tiebreak)"
             if summary["rank_by"] == "density" else "capped units")
    console.print(f"[bold]top 10 clusters by {label}:[/]")
    _print_clusters(summary["top_clusters"])


def _print_clusters(rows) -> None:
    """Shared renderer for a ranked cluster list -- `loci address-gaps` and
    `loci clusters` print the SAME columns in the same order, so the two can
    never disagree about what a cluster's density is."""
    for row in rows:
        d = row.get("cluster_density_400m")
        dens = f"{d:>9,.0f}" if d is not None and d == d else "        —"
        # emoji=False: cluster_id is "{borough}:{lead_category}:{n}" (e.g.
        # "BK:bank:12") and rich's default emoji shortcode parsing mangles
        # ":bank:" into a bank-emoji glyph, garbling the id -- data-derived
        # text with colons must never be printed with emoji parsing on.
        # D84: the frame is printed because a street cluster has NO residents
        # and no tax lot -- its feasibility is not assessed and its density is
        # a catchment over OTHER rows' homes. Reading one as a lot cluster is
        # the misread this column exists to prevent.
        fr = row.get("frame") or "lot"
        console.print(
            f"  {row['cluster_id']:28} {row['borough']:3} {fr:6} "
            f"lead={row['lead_category']:14} "
            f"density={dens} u/km²  units_capped={row['units_capped']:>8,.0f}  "
            f"n_addr={row['n_addresses']:>5}  "
            f"median_lead_excess_m={row['median_lead_excess_m']:>7.0f}"
            + (f"  {row['neighborhood']}" if row.get("neighborhood") else ""),
            emoji=False,
        )


@app.command(name="clusters")
def clusters_cmd(
    boroughs: str = typer.Option("MN,BK", help="Comma-separated boroughs; D78 scope is MN+BK."),
    rank_by: str = typer.Option("density", "--rank-by",
                                help="'density' (owner ruling 2026-09-13, default) or 'units'."),
    category: str = typer.Option("", help="Restrict to clusters with this lead category."),
    frame: str = typer.Option("all", "--frame",
                              help="'lot' (residential tax lots, the pre-D84 list), "
                                   "'street' (the street-midpoint frame: no residents, no "
                                   "tax lot, feasibility not assessed) or 'all' (default, "
                                   "both, with the frame printed on every row). Clusters are "
                                   "built WITHIN a frame (D84), so this never splits one."),
    min_addresses: int = typer.Option(1, "--min-addresses",
                                      help="Drop clusters with fewer than this many member "
                                           "addresses. Density ranks a one-lot cluster against "
                                           "a 700-lot one on equal terms, and nine of the "
                                           "MN+BK top-50 by density are single addresses; this "
                                           "is the knob for reading the list as an investable "
                                           "corridor rather than a doorway. Default 1 = no "
                                           "filter, because the floor is the owner's to set."),
    limit: int = typer.Option(25, help="How many clusters to print (0 = all)."),
    out: str = typer.Option("", help="Also write the FULL ranked table to this CSV path."),
) -> None:
    """List gap clusters in rank order. READ-ONLY -- reads the screen tables
    `loci address-gaps` and `loci supply-ratio` already wrote, and recomputes
    nothing, so it is the cheap way to see the ordering without re-running the
    15 Dijkstra passes.

    THE ORDER IS DENSITY (owner ruling, 2026-09-13: "rank by density", read as
    households per km² inside the walk-shed). A cluster's density is the
    `units_capped`-weighted MEDIAN of its member addresses' own `density_400m`
    -- not Σhomes/Σarea, because member walk-sheds overlap almost entirely at
    a 200 m clustering radius and that ratio is neither a density nor stable
    under how the block was cut into tax lots. `Σ units_capped` is the
    tiebreak and is still printed: "how dense" and "how many" are different
    questions. `--rank-by units` restores the pre-ruling order for comparison.

    Density is a UNITS count per km², from PLUTO UnitsRes -- a register count
    with no margin of error and no occupancy adjustment. It is NOT an ACS
    household density and must not be compared with one like-for-like."""
    from loci.model import address_gaps as ag

    if rank_by not in ag.RANK_BY:
        raise typer.BadParameter(f"--rank-by must be one of {ag.RANK_BY}; got {rank_by!r}")
    boros = [x.strip().upper() for x in boroughs.split(",") if x.strip()]
    con = locidb.connect(read_only=True)
    holes = ", ".join("?" for _ in boros)
    params = list(boros)
    where = f"cluster_id IS NOT NULL AND borough IN ({holes})"
    if category:
        where += " AND lead_category = ?"
        params.append(category)
    if frame.lower() != "all":
        if frame.lower() not in ag.FRAMES:
            raise typer.BadParameter(f"--frame must be 'all' or one of {ag.FRAMES}")
        where += " AND frame = ?"
        params.append(frame.lower())
    df = con.execute(
        f"""SELECT address_id, borough, frame, cluster_id, units_capped, lead_category,
                   lead_excess_m, nta_code, neighborhood, density_400m, walkshed_km2_400m
            FROM analysis.address WHERE {where}""", params).fetchdf()
    if df.empty:
        console.print(f"[yellow]no clustered gap addresses for {boros}"
                      f"{' lead=' + category if category else ''} — "
                      f"run `loci address-gaps` first[/]")
        raise typer.Exit(0)

    try:
        table = ag.cluster_table(df, rank_by=rank_by)
    except ValueError as exc:
        raise typer.BadParameter(str(exc)) from exc

    n_all = len(table)
    if min_addresses > 1:
        table = table[table["n_addresses"] >= min_addresses].reset_index(drop=True)
    label = ("walk-shed density (units/km², units_capped-weighted median)"
             if rank_by == "density" else "capped units")
    console.print(f"{len(table):,} clusters over {len(df):,} gap addresses in "
                  f"{'+'.join(boros)}; ordered by [bold]{label}[/]"
                  + (f" [dim](of {n_all:,}; {n_all - len(table):,} dropped under "
                     f"--min-addresses {min_addresses})[/]" if min_addresses > 1 else ""))
    _print_clusters(table.head(limit if limit else len(table)).to_dict("records"))
    if out:
        table.to_csv(out, index=False)
        console.print(f"[green]ok[/] wrote {len(table):,} rows -> {out}")


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
    # bbl -> address_id for the webmap search box (D99, AC-14) -- lot-frame
    # rows only; see write_address_index()'s own docstring.
    written["address_index.json"] = wx.write_address_index(con, boros, out_dir)
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
    # The DENOMINATOR of the owner's density ruling, printed beside the
    # nominal disc it deliberately is not: a reader has to be able to see that
    # the shed is measured and not assumed.
    nominal = 3.141592653589793 * (radius_m / 1000.0) ** 2
    console.print(
        f"walk-shed area ({report['shed_crs']}, convex hull of the reachable nodes): "
        f"p10 {report['shed_km2_p10']:.3f} · median [bold]{report['shed_km2_median']:.3f}[/] · "
        f"p90 {report['shed_km2_p90']:.3f} km² "
        f"[dim](nominal disc πr² = {nominal:.3f} km²; median permeability "
        f"{report['shed_km2_median'] / nominal:.2f}×)[/]; "
        f"{report['shed_at_floor']:,} at the {sr.MIN_SHED_KM2:.5f} km² floor")
    console.print(
        f"median density_400m: [bold]{report['density_median']:,.0f}[/] residential units "
        f"per km² of reachable walk "
        f"[dim](PLUTO UnitsRes — a register count with NO margin of error; not ACS "
        f"households per km², and not comparable with one)[/]")

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


@app.command(name="transit-profile")
def transit_profile(
    boroughs: str = typer.Option("MN,BK", help="Comma-separated borough codes, or ALL."),
    radius_m: float = typer.Option(400.0, "--radius-m",
                                   help="Catchment radius in NETWORK metres (default 400)."),
    months: int = typer.Option(3, "--months",
                               help="How many of the ridership feed's latest FULL months "
                                    "to average."),
    complex_point: bool = typer.Option(False, "--complex-point",
                                       help="Snap each complex to its published point "
                                            "instead of splitting over entrances."),
    re_sweep: bool = typer.Option(False, "--re-sweep",
                                  help="Force the Dijkstra sweep even when "
                                       "analysis.address_entrance already covers the "
                                       "scope. Needed after a new walk graph or a "
                                       "changed radius, and after `loci address-gaps` "
                                       "(which destroys the rows)."),
    refresh: bool = typer.Option(False, "--refresh",
                                 help="Re-pull the MTA feeds instead of using data/raw/mta."),
    dry_run: bool = typer.Option(False, "--dry-run", help="Compute and print; write nothing."),
) -> None:
    """Walkable subway ENTRIES by DAY TYPE and TIME OF DAY, at address grain.

        analysis.address_transit_profile   one row per address per day_type per
                                           daypart (3 x 5 = 15 cells)
        analysis.address_entrance          the persisted reachable-entrance set
        analysis.address.transit_am_pm_share_400m

    A single average-weekday total mixes populations a retail lead needs
    separated: the resident tapping in at 8am and the office worker tapping in
    at 6pm are the same number today. Day types are weekday / saturday /
    sunday (federal holidays excluded entirely, as before). Dayparts are
    early 00-06, am_peak 06-10, midday 10-15, pm_peak 15-19, evening 19-24 --
    chosen so each NYC DOT count window (AM 07-09, MD 12-14, PM 16-19) falls
    strictly inside one of them, which is what lets `loci validate-pedestrian`
    compare a counted window to a measured one.

    CONSERVATION IS ASSERTED TWICE. The five weekday dayparts must re-sum to
    the incumbent per-complex average-weekday total (two independent
    server-side aggregations of the same rows), and then again to
    `analysis.address.transit_entries_400m` on every address. A failure raises
    and writes nothing: the scalar column and the profile must never disagree.

    THE SWEEP RUNS ONCE. `analysis.address_entrance` persists (address_id,
    entrance_id, dist_m) so a different window, a sixth daypart or a non-even
    split is a JOIN, not another hour of Dijkstra. This command reuses it
    automatically; `--re-sweep` forces the sweep.

    `transit_am_pm_share_400m` is am_peak / pm_peak entries: > 1 is a
    RESIDENTIAL (morning-outbound) catchment, < 1 a job-centre one. A TYPE
    classifier, not a level, and NULL where pm_peak is zero.

    Requires `loci address-access` to have run for the same boroughs. Nothing
    here enters gap_score, supply_ratio_vs_base or any recommendation grade.
    """
    from loci.model import address_transit_profile as atp
    from loci.sources.cities.nyc import mta_ridership as mr

    boros = _parse_boroughs(boroughs)
    con = locidb.connect(read_only=dry_run)
    if not dry_run:
        locidb.init_schema(con)

    reach = None if re_sweep else atp.load_reachable(con, boros)
    if reach is not None:
        console.print(f"[dim]reusing analysis.address_entrance: {len(reach):,} "
                      f"(address, entrance) pairs -- no Dijkstra sweep.[/]")
    else:
        console.print("[dim]no persisted reachable set for this scope; sweeping the "
                      "walk graph (this is the slow path, tens of minutes)…[/]")

    long_df, reach, report = atp.build_transit_profile(
        con, boros, radius_m=radius_m, months=months,
        use_entrances=not complex_point, refresh=refresh, reachable=reach,
        dry_run=dry_run)

    t = report["transit"]
    console.print(f"ridership {t['dataset_id']} · window [bold]{report['window']}[/] · "
                  f"weekdays {t['n_days_by_type']['weekday']}, saturdays "
                  f"{t['n_days_by_type']['saturday']}, sundays "
                  f"{t['n_days_by_type']['sunday']} (federal holidays excluded) · "
                  f"{t['complexes']:,} complexes · {t['entrances']:,} entry-allowed doors")
    c = report["conservation"]
    console.print(f"[green]conservation[/] weekday dayparts re-sum to the incumbent "
                  f"complex total: {c['weekday_total_from_profile']:,.1f} vs "
                  f"{c['weekday_total_incumbent']:,.1f} entries/weekday, worst relative "
                  f"error {c['worst_relative_error']:.2e} over {c['complexes_checked']} "
                  f"complexes")
    r = report["rebuild"]
    console.print(f"[green]conservation[/] and to analysis.address.transit_entries_400m "
                  f"on {r['addresses_compared']:,} addresses: worst relative error "
                  f"{r['worst_relative_error']:.2e}")
    console.print(f"{report['addresses_with_an_entrance']:,} addresses have >=1 entrance "
                  f"within {report['radius_m']:.0f} m ({report['pairs']:,} pairs, source: "
                  f"{report['source']}); every other address is 0.0 in all 15 cells")

    wide = long_df.pivot_table(index="address_id", columns=["day_type", "daypart"],
                               values="transit_entries_400m", aggfunc="sum").fillna(0.0)
    tab = Table(title=f"walkable subway entries per average day — {','.join(boros)} "
                      f"@ {report['radius_m']:.0f} m network "
                      f"(addresses with >=1 entrance only)")
    for col, j in (("day type", "left"), ("daypart", "left"), ("hours", "left"),
                   ("p50", "right"), ("p90", "right"), ("max", "right")):
        tab.add_column(col, justify=j)
    bounds = {n: (a, b) for n, a, b in mr.DAYPARTS}
    for d in mr.DAY_TYPES:
        for pnm in mr.DAYPART_NAMES:
            if (d, pnm) not in wide.columns:
                continue
            v = wide[(d, pnm)]
            a, b = bounds[pnm]
            tab.add_row(d, pnm, f"{a:02d}-{b:02d}", f"{v.median():,.0f}",
                        f"{v.quantile(0.9):,.0f}", f"{v.max():,.0f}")
    console.print(tab)

    if dry_run:
        console.print("[dim]--dry-run:[/] nothing written.")
        raise typer.Exit(0)
    w = report["_written"]
    console.print(f"[green]ok[/] {w['address_transit_profile_rows']:,} rows -> "
                  f"analysis.address_transit_profile · "
                  f"{w['address_entrance_rows']:,} rows -> analysis.address_entrance · "
                  f"{w['addresses_with_share']:,} addresses carry an AM/PM share")


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

    t = Table(title="Spearman rho vs DOT observed whole-round count (AM+MD+PM)")
    for c, j in (("measure", "left"), ("rho (all)", "right"), ("N", "right"),
                 ("rho (Brooklyn)", "right"), ("N", "right")):
        t.add_column(c, justify=j)
    for k, v in report["correlations"].items():
        t.add_row(k, f"{v['spearman_rho']:+.3f}", str(v["n"]),
                  f"{v['spearman_rho_bk']:+.3f}", str(v["n_bk"]))
    console.print(t)

    t2 = Table(title="Per-window: each DOT count window vs the daypart that CONTAINS it")
    for c, j in (("DOT window", "left"), ("hours", "left"), ("daypart", "left"),
                 ("hours", "left"), ("rho (all)", "right"), ("N", "right"),
                 ("rho (Brooklyn)", "right"), ("N", "right"), ("best off-diagonal", "left")):
        t2.add_column(c, justify=j)
    for win, v in report["by_window"].items():
        off = {k: r for k, r in v["off_diagonal"].items() if k != v["daypart"]}
        bk = max(off, key=lambda k: off[k])
        t2.add_row(win.upper(), f"{v['dot_window_hours'][0]:02d}-{v['dot_window_hours'][1]:02d}",
                   v["daypart"],
                   f"{v['daypart_hours'][0]:02d}-{v['daypart_hours'][1]:02d}",
                   f"{v['spearman_rho']:+.3f}", str(v["n"]),
                   f"{v['spearman_rho_bk']:+.3f}", str(v["n_bk"]),
                   f"{bk} {off[bk]:+.3f}")
    console.print(t2)
    console.print("[dim]the off-diagonal is the sharper test: if the AM count is ranked "
                  "as well by pm_peak as by am_peak, the daypart split is carrying no "
                  "information and the measure is a station on/off flag.[/]")
    console.print(f"[yellow]{report['points_with_zero_transit']} of "
                  f"{report['points']}[/] count points have transit = 0 "
                  f"(no entrance within {report['radius_m']:.0f} m network) — a tie block "
                  f"that lands wherever ties land; "
                  f"{report['points_with_zero_transit_bk']} of "
                  f"{report['brooklyn_points']} Brooklyn points")
    console.print("[dim]saturday and sunday dayparts are UNVALIDATED: DOT counts "
                  "weekdays, so there is no counterpart to correlate them against.[/]")
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
    record: bool = typer.Option(False, "--record",
                                help="Also APPEND this card to analysis.recommendation "
                                     "(one row per category). Default off: reading a card "
                                     "is not claiming one."),
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

    if record:
        # THE LEDGER HOOK (2026-09-14). Records the WHOLE card -- the D verdicts
        # included -- because the "do not act" rows are the control group: if
        # they fill as fast as the C rows, the screen carries no information and
        # nothing else in this project would tell us. Idempotent on card_hash,
        # so re-running an unchanged card writes nothing.
        import datetime as _dt

        from loci.model import recommendation_ledger as rl

        gap = None
        if box or nta:
            where, params = rec._area_predicate(box, nta)
            holes = ", ".join("?" for _ in boros)
            gap = con.execute(
                f"SELECT median(a.gap_score) FROM analysis.address_gaps a "
                f"WHERE a.borough IN ({holes}) AND {where} "
                f"AND COALESCE(a.frame, 'lot') = 'lot'",
                [*boros, *params]).fetchone()[0]
        # A bbox card has no storefront: its anchor is the box centroid, and
        # sql/026 caveat 5 says so on every distance it produces.
        if box:
            kind, aid = "bbox", ",".join(f"{v:g}" for v in box)
            alon, alat = (box[1] + box[3]) / 2, (box[0] + box[2]) / 2
        else:
            kind, aid = "nta", nta
            alon, alat = con.execute(
                "SELECT median(lon), median(lat) FROM analysis.address "
                "WHERE nta_code = ? AND COALESCE(frame, 'lot') = 'lot'",
                [nta]).fetchone()
        rows = rl.rows_from_cards(
            cards, facts, issued_on=_dt.date.today(),
            issued_by=f"loci recommend (rules v{rules.get('version')})",
            area_kind=kind, area_id=aid, area_label=area,
            anchor_lon=alon, anchor_lat=alat, gap_score=gap)
        # DuckDB refuses two connections to one file with different
        # configurations in the same process, so the read-only card connection
        # has to go before the ledger's write connection opens.
        con.close()
        wcon = _recs_connect(read_only=False)
        res = rl.insert_rows(wcon, rows)
        console.print(f"[green]recorded[/] {res.n_written} of {res.n_offered} rows to "
                      f"analysis.recommendation ({res.n_duplicate} already held). "
                      f"Check them monthly with `loci recommendations check`.")


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
    for cat, c in (report.get("capacity") or {}).items():
        console.print(
            f"[dim]capacity ({cat}): {c['capacity_bound']:,}/{c['rows']:,} rows "
            f"({(c['capacity_bound_share'] or 0):.1%}) bound by the square-footage ceiling · "
            f"median model p50 ${c['median_model_p50_before_cap_usd'] or 0:,.0f} -> shipped "
            f"${c['median_shipped_p50_usd'] or 0:,.0f} (median cap "
            f"${c['median_cap_p50_usd'] or 0:,.0f}) · "
            f"{c['area_from_typical_footprint']:,} rows used the category-typical footprint "
            f"because PLUTO reports no retail area on the lot · "
            f"{c['area_split_by_storefront_count']:,} rows split a lot's retail area across "
            f"more than one registered storefront[/]")
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
    # `lambda_field` is the calibration's own word for which lambda the shipped
    # model uses (v0 the EC-mean one, v0.2 the median-anchored one). Reading it
    # back rather than hardcoding a field name is what stops this table showing
    # a number the model does not use.
    lam_key = ((doc.get("settings") or {}).get("anchor_statistic") == "median"
               and "lambda_median" or "lambda_per_store")
    for col, j in (("category", "left"), ("beta", "right"), ("gamma", "right"),
                   ("eps", "right"), ("delta", "right"),
                   ("competition", "left"), ("lambda BK", "right"),
                   ("lambda MN", "right"), ("anchor $/estab BK", "right"),
                   ("rho oos", "right"), ("vs county", "right"), ("vs homes", "right"),
                   ("placebo", "center"), ("gate", "center")):
        t.add_column(col, justify=j)
    for cat, d in doc["categories"].items():
        bt = d.get("backtest") or {}
        lam = d.get("lambda") or {}
        pl = d.get("placebo") or {}
        colour = "green" if d.get("gate") == "pass" else "red"

        def _l(f):
            v = (lam.get(f) or {}).get(lam_key)
            if v is None:
                v = (lam.get(f) or {}).get("lambda_per_store")
            return "—" if v is None else f"{v:.3f}"
        _bk = lam.get("047") or {}
        ec = _bk.get("median_anchor_usd" if lam_key == "lambda_median"
                     else "ec_rev_per_estab_usd") or _bk.get("ec_rev_per_estab_usd")
        t.add_row(cat, "—" if d.get("beta") is None else f"{d['beta']:.2f}",
                  "—" if d.get("gamma") is None else f"{d['gamma']:+.2f}",
                  "—" if d.get("epsilon") is None else f"{d['epsilon']:.1f}",
                  "—" if d.get("delta") is None else f"{d['delta']:.1f}",
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

    First-seen comes from `analysis.poi_first_seen` (the ledger built by
    `loci poi-snapshot`), NOT from the sources directly -- run that first or
    this command raises rather than reporting every brand as undated.

    `locations_new_12m` is still a FLOOR, counted over `locations_dated`, which
    is printed beside it together with the three-way split: dated BY SOURCE,
    dated BY OBSERVATION (the ledger saw it appear), and LEFT-CENSORED (already
    there when the ledger started; opening date unknown). The censored share is
    the part that shrinks every month the ledger runs."""
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
    n = max(result.n_locations, 1)
    console.print(
        f"[dim]{result.n_locations:,} brand-locations by first-seen kind: "
        f"{result.n_by_source:,} ({result.n_by_source / n:.0%}) dated BY SOURCE, "
        f"{result.n_observed:,} ({result.n_observed / n:.0%}) dated BY OBSERVATION "
        f"(the month Loci first saw it), "
        f"{result.n_censored:,} ({result.n_censored / n:.0%}) LEFT-CENSORED "
        f"(existed when the ledger started; opening date unknown).[/]")
    console.print(
        f"[dim]`new 12m` is a floor over the {result.n_dated:,} dated "
        f"({result.n_dated / n:.0%}); the censored share shrinks every month the "
        f"ledger runs. Never read a censored location as an opening.[/]")
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
    """poi-snapshot -> detect -> research -> render. The monthly job
    (`make chains-refresh`).

    Research failure does NOT abort the run: the snapshot is the load-bearing
    artefact and it is already written by then, so a Tavily outage must not
    cost the month its count."""
    console.rule("[bold]1/4 poi-snapshot (first-seen ledger)")
    # BEFORE detect, always: detect reads the ledger and raises without it, and
    # a month whose ledger row is missing can never be recovered afterwards --
    # the observation is gone once the month is.
    poi_snapshot(month=month, dry_run=dry_run, force=False)
    console.rule("[bold]2/4 detect")
    chains_detect(month=month, dry_run=dry_run, limit=25)
    if skip_research:
        console.rule("[bold]3/4 research — skipped (--skip-research)")
    else:
        console.rule("[bold]3/4 research")
        try:
            chains_research(month=month, max_queries=max_queries, days=None,
                            detected=0, dry_run=dry_run)
        except typer.Exit as exc:
            if exc.exit_code:
                console.print("[yellow]research failed — continuing to render; "
                              "the snapshot is already written.[/]")
        except Exception as exc:            # noqa: BLE001
            console.print(f"[yellow]research failed ({exc}) — continuing to render.[/]")
    console.rule("[bold]4/4 render")
    try:
        chains_render(month=month, out=None, dry_run=dry_run)
    except typer.Exit as exc:
        if exc.exit_code:
            raise


if __name__ == "__main__":
    app()


# ===========================================================================
# `loci filings` -- the government-filing lifecycle (GTM, 2026-09-13)
#
# Appended at the END of this file on purpose: three concurrent threads hold
# hunks above, and a block that only adds lines at the bottom cannot conflict
# with any of them. `app` is already constructed; Typer registers on import,
# and the installed entry point is `loci.cli:app` (pyproject [project.scripts]),
# so the placement after the __main__ guard changes nothing about how the CLI
# is invoked.
# ===========================================================================

filings_app = typer.Typer(add_completion=False, help=(
    "When a store goes live, read off what it had to declare to the government. "
    "Seven feeds -- SLA pending, DOB NOW job filings, DCWP applications, DOB NOW "
    "permits, DCWP licences, SLA active, DOHMH first inspection -- normalised "
    "into ONE table, staging.storefront_filing, one row per dated filing event. "
    "Not only chains: an independent operator announces nothing to the press and "
    "everything to the City."))
app.add_typer(filings_app, name="filings")


def _filings_connect(read_only: bool = False):
    """Open the warehouse, retrying the lock a concurrent writer holds.

    Same posture as `_chains_connect`: another session rebuilding
    analysis.address is the normal state in this project, not an error. Backs
    off rather than failing the whole ingest after a 60-second Socrata pull."""
    import time

    import duckdb

    last = None
    for attempt in range(6):
        try:
            con = locidb.connect(read_only=read_only)
            if not read_only:
                locidb.init_schema(con)
            return con
        except duckdb.IOException as exc:       # lock held by a peer session
            last = exc
            time.sleep(5 * 2 ** attempt)
    raise RuntimeError(
        f"filings: the DuckDB file stayed write-locked across 6 attempts ({last}). "
        f"Another session is holding it; retry when it finishes.")


@filings_app.command("ingest")
def filings_ingest(
    source: list[str] = typer.Option(None, "--source",
                                     help="Repeatable. Default: all seven feeds."),
    asof: str = typer.Option(None, "--asof", help="YYYY-MM-DD; default today. "
                                                  "Sets the 24-month window."),
    limit: int = typer.Option(None, "--limit", help="Cap rows per feed (probing)."),
    refresh: bool = typer.Option(False, "--refresh",
                                 help="Ignore data/raw/<source>/ and re-pull."),
    dry_run: bool = typer.Option(False, "--dry-run",
                                 help="Fetch, normalise, geocode, report -- write nothing."),
) -> None:
    """Pull the filing feeds, resolve each to a BBL, write staging.storefront_filing.

    Idempotent per source: the write DELETEs only the sources named in this run,
    so `--source nyc_sla_pending_licenses` cannot erase the other six.

    Every feed FAILS LOUD. A `$where` that matches nothing raises rather than
    ingesting a silent zero, because "no business filed anything in New York for
    two years" and "the column was renamed" are the same HTTP 200.
    """
    import datetime as _dt

    from loci.model import storefront_filing as sf
    from loci.sources.cities.nyc.filing_feeds import FEEDS, dob_now_where

    asof_d = _dt.date.fromisoformat(asof) if asof else _dt.date.today()
    sources = list(source) if source else list(FEEDS)

    con = _filings_connect(read_only=False)
    console.rule("[bold]1/4 PLUTO lot index")
    n_lots = sf.build_pluto_index(con)
    console.print(f"  {n_lots:,} lots, five boroughs, all land uses")

    console.rule(f"[bold]2/4 fetch + geocode ({len(sources)} feed(s))")
    frame, report = sf.assemble(con, sources, asof=asof_d, limit=limit,
                                use_cache=not refresh)

    t = Table(title=f"rows per source x stage — asof {report['asof']}")
    for col in ("source", "stage", "rows"):
        t.add_column(col)
    for row in report["stage_counts"]:
        t.add_row(row["source"], row["stage"], f"{row['n']:,}")
    console.print(t)

    m = Table(title="BBL match method")
    for col in ("source", "match_method", "rows"):
        m.add_column(col)
    for row in report["match_counts"]:
        m.add_row(row["source"], row["match_method"], f"{row['n']:,}")
    console.print(m)

    console.print(f"  dropped, no event date or id: {report['dropped_no_date_or_id']:,}")
    console.print(f"  collapsed to earliest, duplicate filing_id (permit renewals, "
                  f"repeated licence rows): {report['dropped_duplicate_filing_id']:,}")
    for src, n in sorted(report["duplicate_rows_by_source"].items()):
        console.print(f"    {src}: {n:,} rows in duplicated groups")
    console.print(f"  name key NULL (junk name): {report['name_key_null']:,}")
    if "nyc_dob_now_job_filings" in sources:
        console.print(Panel(dob_now_where(asof_d),
                            title="DOB NOW storefront filter (server-side)"))

    if dry_run:
        console.print("[yellow]--dry-run: staging.storefront_filing not written.[/]")
        raise typer.Exit(0)

    console.rule("[bold]3/4 write")
    n = sf.write(con, frame, sources)
    console.print(f"[green]written[/] {n:,} rows into {sf.TABLE}")

    console.rule("[bold]4/4 validate")
    problems = sf.validate(con, frame, sources)
    for p in problems:
        console.print(f"[red]FAIL[/] {p}")
    if problems:
        raise typer.Exit(1)
    console.print("[green]ok[/] row counts and source x stage totals agree with the build")


@filings_app.command("stats")
def filings_stats() -> None:
    """Rows per source x stage, BBL match rates, and the LEAD-TIME distribution.

    The lead time is the point of the exercise: median days from a business's
    earliest application-side filing to its earliest terminal one (DCWP licence
    issued, or DOHMH's first real inspection), paired within one BBL and split
    by the feed's own category text.

    Read `model/storefront_filing`'s docstring before quoting it. The pairing is
    conditioned on both rows resolving to the same BBL, applications that never
    opened contribute nothing, and the 24-month window right-censors the tail --
    so the median is a lower bound among successes, not a schedule.
    """
    from loci.model import storefront_filing as sf

    con = _filings_connect(read_only=True)
    out = sf.stats(con)

    t = Table(title="staging.storefront_filing — source x stage")
    for col in ("source", "stage", "filings", "name keys", "BBLs", "first", "last"):
        t.add_column(col)
    for r in out["census"].itertuples(index=False):
        t.add_row(r.source, r.stage, f"{r.n_filings:,}", f"{r.n_name_keys:,}",
                  f"{r.n_bbl:,}", str(r.first_filed_on), str(r.last_filed_on))
    console.print(t)

    m = Table(title="BBL match rate")
    for col in ("source", "rows", "with BBL", "% BBL", "with name key"):
        m.add_column(col)
    for r in out["match_rate"].itertuples(index=False):
        m.add_row(r.source, f"{r.n:,}", f"{r.n_bbl:,}", f"{r.pct_bbl}",
                  f"{r.n_name_key:,}")
    console.print(m)

    d = Table(title="match method detail")
    for col in ("source", "method", "rows", "% of source"):
        d.add_column(col)
    for r in out["match"].itertuples(index=False):
        d.add_row(r.source, r.match_method, f"{r.n:,}", f"{r.pct_of_source}")
    console.print(d)

    pairs = out["lead_pairs"]
    if not len(pairs):
        console.print("[yellow]no (business_name_key, bbl) pairs with both an early "
                      "and a terminal stage — nothing to measure yet.[/]")
        return

    sp = Table(title="lead time by stage pair — THE SPLIT THAT MATTERS")
    for col in ("kind", "first stage", "terminal stage", "N", "p25", "median", "p75"):
        sp.add_column(col)
    for r in pairs.itertuples(index=False):
        sp.add_row(r.pair_kind, r.first_stage, r.open_stage, f"{r.n:,}",
                   f"{r.p25_days:.0f}", f"{r.median_days:.0f}", f"{r.p75_days:.0f}")
    console.print(sp)
    console.print("[yellow]`same_agency_processing` is DCWP application -> DCWP "
                  "licence: the agency's own clock, NOT a time-to-open. Never pool "
                  "it with the cross-agency rows below.[/]")

    for label, key in (("CROSS-AGENCY — time from first filing to first "
                        "inspection / licence issued (days)", "lead"),
                       ("SAME-AGENCY — DCWP application to DCWP licence "
                        "(processing time, days)", "lead_same_agency")):
        frame = out[key]
        if not len(frame):
            continue
        lt = Table(title=label)
        for col in ("category_hint", "N", "p25", "median", "p75", "min", "max"):
            lt.add_column(col)
        for r in frame.itertuples(index=False):
            lt.add_row(str(r.category_hint)[:40], f"{r.n:,}", f"{r.p25_days:.0f}",
                       f"{r.median_days:.0f}", f"{r.p75_days:.0f}",
                       f"{r.min_days:.0f}", f"{r.max_days:.0f}")
        console.print(lt)
    console.print("[dim]Conditioned on both rows resolving to the same BBL; "
                  "applications that never opened contribute nothing; the "
                  "24-month window right-censors the tail (median biased down).[/]")


# ===========================================================================
# `loci storefront-pipeline` -- stage two of the government-filing lifecycle.
#
# APPENDED AT THE VERY END OF THIS FILE ON PURPOSE. Two peer sessions hold
# hunks above (D78's address-gaps scope guard, D81's revenue calibration), and
# a block inserted mid-file would conflict with both. Nothing above this line
# is touched.
# ===========================================================================
storefront_pipeline_app = typer.Typer(add_completion=False, help=(
    "Roll the filing event log up into one row per BUSINESS TRYING TO OPEN at "
    "a lot, reconcile the same store's filings across agencies, date the "
    "first-seen ledger from what opened, and carry the coming-supply context "
    "onto every address. Stage one (`loci filings`) is the event log; this is "
    "the lifecycle."))
app.add_typer(storefront_pipeline_app, name="storefront-pipeline")


def _pipeline_connect(read_only: bool = False):
    """Open the warehouse, retrying the lock a concurrent writer holds.

    Same posture as `_filings_connect` and `_chains_connect`: another session
    rebuilding analysis.address is the normal state in this project (D69), not
    an error, so back off rather than failing a run that has already done the
    expensive part."""
    import time

    import duckdb

    last = None
    for attempt in range(6):
        try:
            con = locidb.connect(read_only=read_only)
            if not read_only:
                locidb.init_schema(con)
            return con
        except duckdb.IOException as exc:        # lock held by a peer session
            last = exc
            time.sleep(5 * 2 ** attempt)
    raise RuntimeError(
        f"storefront-pipeline: the DuckDB file stayed write-locked across 6 "
        f"attempts ({last}). Another session is holding it; retry when it "
        f"finishes.")


@storefront_pipeline_app.command("build")
def storefront_pipeline_build(
    asof: str = typer.Option(None, "--asof",
                             help="YYYY-MM-DD; default today. Stamped on every row."),
    no_reconcile: bool = typer.Option(False, "--no-reconcile",
                                      help="Skip the cross-agency name link. The strict "
                                           "(same-name-key) lead times are unaffected."),
    dry_run: bool = typer.Option(False, "--dry-run",
                                 help="Roll up, reconcile, report -- write nothing."),
) -> None:
    """Build analysis.storefront_pipeline from staging.storefront_filing.

    One row per (bbl, business_name_key), with the two D75 carry rules: a
    filing with no BBL, or no usable name key, is kept as its OWN row and
    FLAGGED rather than dropped -- and specifically is NOT grouped on the key
    it does have, because grouping a nameless filing on its lot would fuse the
    laundromat, the deli and the nail salon into one business, and grouping a
    lot-less filing on its name would pair a Bronx application with a Brooklyn
    inspection.

    Then the CROSS-AGENCY LINK. The lead-time N is small because the same store
    files under different names at different agencies -- 11,813 BBLs carry both
    an early and a terminal stage under name keys that do not match. The link
    pairs an unopened early row with an opened row on the SAME BBL inside 540
    days when their names share a RARE token, or when the lot offers exactly
    one candidate on each side. It is one-to-one and greedy, because a
    many-to-many link would turn one build-out into several lead times.

    A LINK IS AN INFERENCE; A SHARED NAME KEY IS AN OBSERVATION. `stats` prints
    strict and reconciled side by side and never pools them.

        loci storefront-pipeline build
    """
    import datetime as _dt

    from loci.model import storefront_pipeline as sp

    asof_d = _dt.date.fromisoformat(asof) if asof else _dt.date.today()
    con = _pipeline_connect(read_only=dry_run)

    console.rule("[bold]1/3 roll up + reconcile")
    df, report = sp.build(con, asof=asof_d, dry_run=dry_run,
                          reconcile_links=not no_reconcile)

    g = Table(title=f"analysis.storefront_pipeline — asof {report['asof']}")
    for col in ("measure", "value"):
        g.add_column(col)
    g.add_row("filing events rolled up", f"{report['filings']:,}")
    g.add_row("pipeline rows", f"{report['rows']:,}")
    for kind, n in sorted(report["by_group_kind"].items()):
        g.add_row(f"  group_kind = {kind}", f"{n:,}")
    g.add_row("open (first_inspection | license_issued | liquor_active)",
              f"{report['open']:,}")
    g.add_row("not yet open", f"{report['not_open']:,}")
    g.add_row("rows with NO BBL (carried, flagged — D75)", f"{report['bbl_missing']:,}")
    g.add_row("rows with NO name key (carried, flagged — D75)",
              f"{report['name_key_missing']:,}")
    g.add_row("with a measured lead time", f"{report['with_lead_days']:,}")
    g.add_row("categorised (filing_categories.yaml "
              f"v{report['category_map_version']})", f"{report['categorised']:,}")
    for conf, n in sorted(report["category_confidence"].items()):
        g.add_row(f"  confidence = {conf}", f"{n:,}")
    g.add_row("point from a filing / from a PLUTO lot centroid / none",
              f"{report['rows'] - report['points_from_pluto'] - report['points_missing']:,}"
              f" / {report['points_from_pluto']:,} / {report['points_missing']:,}")
    console.print(g)

    if "reconcile" in report:
        r = report["reconcile"]
        l = Table(title="cross-agency reconciliation")
        for col in ("measure", "value"):
            l.add_column(col)
        l.add_row("BBLs with an early AND a terminal row", f"{r['bbls_with_both_sides']:,}")
        l.add_row("candidate pairs inside the window", f"{r['candidate_pairs']:,}")
        l.add_row("links made (one-to-one)", f"{r['links']:,}")
        for m, n in sorted(r["links_by_method"].items()):
            l.add_row(f"  {m}", f"{n:,}")
        l.add_row("terminal rows already strictly matched (excluded)",
                  f"{r['terminal_rows_already_strict']:,}")
        l.add_row("window / min idf", f"{r['window_days']} d / {r['min_idf']}")
        console.print(l)
        console.print("[yellow]`sole_pair_in_bbl` is the WEAKER rule: it says the lot "
                      "offered no other candidate, not that the names agree. Read the "
                      "strict column before quoting a reconciled median.[/]")

    if dry_run:
        console.print("[yellow]--dry-run: analysis.storefront_pipeline not written.[/]")
        raise typer.Exit(0)

    console.rule("[bold]2/3 write")
    console.print(f"[green]written[/] {report['_written']:,} rows into {sp.TABLE}")

    console.rule("[bold]3/3 validate")
    for p in report.get("_problems", []):
        console.print(f"[red]FAIL[/] {p}")
    if report.get("_problems"):
        raise typer.Exit(1)
    console.print("[green]ok[/] every filing lands in exactly one group, the grain "
                  "holds, and every link is symmetric, one-to-one and inside one BBL")


@storefront_pipeline_app.command("ledger")
def storefront_pipeline_ledger(
    asof: str = typer.Option(None, "--asof", help="YYYY-MM-DD; default today."),
    dry_run: bool = typer.Option(False, "--dry-run",
                                 help="Match and report; write nothing."),
) -> None:
    """Date the first-seen ledger from what the government says OPENED.

    Adds the fourth `first_seen_kind`, 'gov_filing', to analysis.poi_presence:
    a deduped location matched to a pipeline row whose `opened_on` is earlier
    than anything a POI source could say -- or which is LEFT-CENSORED, i.e. the
    ledger has no idea when it opened and never will.

    ONLY AN OPEN SIGNAL MAY SET A FIRST-SEEN. The join reads `opened_on`, which
    exists only where a `license_issued`, `liquor_active` or `first_inspection`
    filing exists. An application, a permit and a fit-out filing are dates on
    which somebody INTENDED to open; using one would date a storefront to a
    year before it existed.

    IT CAN ONLY EVER MOVE A DATE EARLIER, and the strict inequality that
    guarantees that is also what makes this idempotent -- a second run updates
    nothing.

        loci storefront-pipeline ledger
    """
    import datetime as _dt

    from loci.model import poi_presence as pp
    from loci.model import storefront_pipeline as sp

    asof_d = _dt.date.fromisoformat(asof) if asof else _dt.date.today()
    con = _pipeline_connect(read_only=dry_run)
    console.print("[dim]matching the first-seen ledger to the filing pipeline "
                  "(PLUTO lot + brand key, then brand key + 100 m)…[/]")
    report = sp.apply_gov_filing(con, asof=asof_d, dry_run=dry_run)

    m = Table(title="ledger x pipeline match")
    for col in ("measure", "value"):
        m.add_column(col)
    m.add_row("ledger rows", f"{report['ledger_rows']:,}")
    m.add_row("locations matched to a pipeline row with an opening date",
              f"{report['matched_locations']:,}")
    for method, n in sorted(report.get("match_methods", {}).items()):
        m.add_row(f"  {method}", f"{n:,}")
    m.add_row("of those, ELIGIBLE (censored, or an earlier date)",
              f"{report.get('eligible', 0):,}")
    for kind, n in sorted(report.get("eligible_by_prior_kind", {}).items()):
        m.add_row(f"  was {kind}", f"{n:,}")
    console.print(m)

    k = Table(title="first_seen_kind distribution")
    for col in ("kind", "before", "after"):
        k.add_column(col)
    for kind in pp.KINDS:
        k.add_row(kind, f"{report['kinds_before'].get(kind, 0):,}",
                  f"{report['kinds_after'].get(kind, 0):,}")
    console.print(k)

    if dry_run:
        console.print("[yellow]--dry-run: analysis.poi_presence not written.[/]")
        raise typer.Exit(0)
    console.print(f"[green]updated[/] {report['updated']:,} ledger rows; "
                  f"[bold]{report['censored_resolved']:,}[/] left-censored rows "
                  f"finally carry a real opening date")
    errors, stats = pp.coverage_check(con)
    for e in errors:
        console.print(f"[red]FAIL[/] {e}")
    if errors:
        raise typer.Exit(1)
    console.print("[green]ok[/] check-presence invariants hold "
                  f"({stats['coverage_pct']:.2f}% of deduped locations covered)")


@storefront_pipeline_app.command("openings")
def storefront_pipeline_openings(
    boroughs: str = typer.Option("MN,BK", help="Comma-separated borough codes, or ALL."),
    asof: str = typer.Option(None, "--asof",
                             help="YYYY-MM-DD; default today. The windows count back "
                                  "from this."),
    radius_m: float = typer.Option(400.0, "--radius-m",
                                   help="Catchment radius in NETWORK metres "
                                        "(default 400 = the 5-min tier)."),
    dry_run: bool = typer.Option(False, "--dry-run", help="Compute and print; write nothing."),
) -> None:
    """Coming supply and just-arrived supply, per category, at address grain.

        openings_pipeline_400m  filings of THIS category in the last 18 months
                                that are NOT YET OPEN, within 400 m network
        openings_recent_400m    of this category, OPENED in the last 12 months,
                                same radius

    CONTEXT MEASURES. UPDATE-only on analysis.address_category, asserted
    disjoint from every column the screen, the supply ratio, the demand
    annotation or the age fit owns. They do NOT enter gap_score,
    supply_ratio_vs_base, supply_400m or any recommendation grade -- a block
    does not become a gap because nothing is being built there, and does not
    stop being one because something is.

    EVERY IN-SCOPE ADDRESS x CATEGORY GETS A NUMBER, and 0 IS A VALUE (owner
    rule: no eligibility gate, every street represented). NULL means this
    command has not run since the last screen rebuild.

    Same engine as homes_400m / jobs_400m / supply_400m: one pruned walk graph,
    one bounded scipy Dijkstra per batch of query nodes, both measures and all
    fifteen categories on ONE sweep. No straight lines anywhere.

    THE HONEST LIMIT: both DOB feeds publish the architect's free-text job
    description, not the tenant's trade, so a row whose only filings are DOB
    rows carries no category and contributes to nothing. These columns are an
    UNDER-COUNT, and thinnest at exactly the earliest stages.

    RE-APPLY AFTER EVERY SCREEN RE-RUN -- `loci address-gaps` destroys the rows
    these columns sit on. `openings_run_at IS NULL` is the flag.

        loci storefront-pipeline openings --boroughs MN,BK
    """
    import datetime as _dt

    from loci.model import storefront_pipeline as sp

    asof_d = _dt.date.fromisoformat(asof) if asof else _dt.date.today()
    boros = _parse_boroughs(boroughs)
    con = _pipeline_connect(read_only=dry_run)
    console.print(f"[dim]openings within {radius_m:.0f} m network for "
                  f"{','.join(boros)}…[/]")
    df, report = sp.build_openings(con, boros, asof=asof_d, radius_m=radius_m,
                                   dry_run=dry_run)

    t = Table(title=f"openings — asof {report['asof']}")
    for col in ("measure", "value"):
        t.add_column(col)
    t.add_row("pipeline rows (total / categorised / categorised + placed)",
              f"{report['pipeline_rows']:,} / {report['categorised']:,} / "
              f"{report['categorised_and_placed']:,}")
    t.add_row(f"in the pipeline window (from {report['pipeline_window_from']}, not open)",
              f"{report['in_pipeline_window']:,}")
    t.add_row(f"in the recent-openings window (from {report['recent_window_from']})",
              f"{report['in_recent_window']:,}")
    t.add_row("addresses swept / distinct graph nodes",
              f"{report['addresses']:,} / {report['query_nodes']:,}")
    t.add_row("address x category rows", f"{report['rows']:,}")
    t.add_row("rows with a NON-ZERO pipeline count",
              f"{report['address_categories_with_pipeline']:,}")
    t.add_row("rows with a NON-ZERO recent count",
              f"{report['address_categories_with_recent']:,}")
    t.add_row("max per address (pipeline / recent)",
              f"{report['max_pipeline_400m']} / {report['max_recent_400m']}")
    t.add_row("graph version", str(report["graph_version"]))
    console.print(t)

    if dry_run:
        console.print("[yellow]--dry-run: analysis.address_category not written.[/]")
        raise typer.Exit(0)
    console.print(f"[green]written[/] {report['_written']:,} address x category rows")
    for p in report.get("_problems", []):
        console.print(f"[red]FAIL[/] {p}")
    if report.get("_problems"):
        raise typer.Exit(1)
    console.print(con.execute(sp.OPENINGS_VALIDATION_SQL).fetchdf()
                  .tail(16).to_string(index=False))
    console.print("[green]ok[/] every in-scope address x category carries both numbers, "
                  "and no catchment holds more filings than the whole table does")


@storefront_pipeline_app.command("stats")
def storefront_pipeline_stats() -> None:
    """The lifecycle, the lead times strict vs reconciled, the ledger kinds,
    the brands with something in the pipeline, and two neighbourhoods.

    Read the lead-time tables as TWO POPULATIONS. `strict` pairs two filings
    that shared a business name key on one lot -- an observation. `reconciled`
    adds pairs the cross-agency link inferred from a rare shared token or from
    a lot with no other candidate. The strict numbers are the reference.

        loci storefront-pipeline stats
    """
    from loci.model import storefront_pipeline as sp

    con = _pipeline_connect(read_only=True)
    if not con.execute(
            "SELECT count(*) FROM information_schema.tables WHERE table_schema = "
            "'analysis' AND table_name = 'storefront_pipeline'").fetchone()[0]:
        console.print("[red]analysis.storefront_pipeline does not exist[/] — run "
                      "`loci storefront-pipeline build` first.")
        raise typer.Exit(1)
    out = sp.stats(con)

    c = Table(title="lifecycle — entry stage x open state")
    for col in ("group_kind", "entry stage", "open", "rows", "filings", "categorised"):
        c.add_column(col)
    for r in out["census"].head(20).itertuples(index=False):
        c.add_row(r.group_kind, r.entry_stage, "yes" if r.is_open else "no",
                  f"{r.n_rows:,}", f"{int(r.n_filings):,}", f"{r.n_categorised:,}")
    console.print(c)

    f = Table(title="furthest stage reached")
    for col in ("furthest stage", "rows", "open", "median lead (d)"):
        f.add_column(col)
    for r in out["furthest"].itertuples(index=False):
        f.add_row(r.furthest_stage, f"{r.n_rows:,}", f"{r.n_open:,}",
                  "—" if r.median_lead_days is None or r.median_lead_days != r.median_lead_days
                  else f"{r.median_lead_days:.0f}")
    console.print(f)

    h = Table(title="LEAD TIME — the three headline pairs, strict vs reconciled")
    for col in ("first stage", "terminal stage", "N strict", "median strict",
                "N reconciled", "median reconciled", "linked pairs added"):
        h.add_column(col)
    for r in out["headline"].itertuples(index=False):
        h.add_row(r.first_stage, r.open_stage, f"{r.n_strict:,}",
                  "—" if r.median_strict is None else f"{r.median_strict:.0f}",
                  f"{r.n_reconciled:,}",
                  "—" if r.median_reconciled is None else f"{r.median_reconciled:.0f}",
                  f"+{r.n_linked:,}")
    console.print(h)
    console.print("[yellow]The STRICT column is the reference. A reconciled median is "
                  "computed over strict pairs PLUS inferred links; the two are different "
                  "populations and must never be quoted as one number.[/]")

    for label, key in (("STRICT — both filings shared a name key on one BBL", "lead_strict"),
                       ("RECONCILED — strict plus cross-agency links", "lead_reconciled")):
        frame = out[key]
        if not len(frame):
            continue
        lt = Table(title=label)
        for col in ("first stage", "terminal stage", "N", "strict", "linked",
                    "p25", "median", "p75"):
            lt.add_column(col)
        for r in frame.itertuples(index=False):
            lt.add_row(r.first_stage, r.open_stage, f"{r.n:,}", f"{r.n_strict:,}",
                       f"{r.n_linked:,}", f"{r.p25_days:.0f}", f"{r.median_days:.0f}",
                       f"{r.p75_days:.0f}")
        console.print(lt)
    console.print("[dim]Same-agency pairs (DCWP application -> DCWP licence, SLA pending "
                  "-> SLA active) are EXCLUDED from both tables: they measure an agency's "
                  "queue, not a build-out.[/]")

    cat = Table(title="category mapping coverage (filings, not rows)")
    for col in ("loci_category", "confidence", "rows", "filings", "not open"):
        cat.add_column(col)
    for r in out["categories"].itertuples(index=False):
        cat.add_row(r.loci_category, r.category_confidence, f"{r.n_rows:,}",
                    f"{int(r.n_filings):,}", f"{r.n_not_open:,}")
    console.print(cat)

    if "kinds" in out:
        k = Table(title="analysis.poi_presence — first_seen_kind")
        for col in ("kind", "rows"):
            k.add_column(col)
        for r in out["kinds"].itertuples(index=False):
            k.add_row(r.first_seen_kind, f"{r.n:,}")
        console.print(k)

    b = Table(title="top 20 brands by NOT-YET-OPEN pipeline rows")
    for col in ("brand_key", "pipeline rows", "BBLs", "boroughs", "first entry",
                "last entry"):
        b.add_column(col)
    for r in out["brands"].itertuples(index=False):
        b.add_row(r.brand_key, f"{r.pipeline_rows:,}", f"{r.pipeline_bbls:,}",
                  str(r.boroughs), str(r.first_entry)[:10], str(r.last_entry)[:10])
    console.print(b)
    console.print("[dim]A FLOOR: franchisee filings go in under the operating company "
                  "(\"PRIYA FOODS INC\" running a Dunkin'), so a brand with no pipeline "
                  "rows may simply be one whose franchisees file under their own names. "
                  "Rows whose ONLY filings come from the two DOB feeds are excluded from "
                  "this ranking: those feeds publish owner_s_business_name, so without "
                  "the filter the twenty biggest \"brands\" in New York are twenty "
                  "property managers.[/]")

    for key, title in (("gowanus", "Gowanus core (bbox, as the recommendation card)"),
                       ("east_village", "East Village (NTA MN0303)")):
        if key not in out:
            console.print("[yellow]openings not computed — run "
                          "`loci storefront-pipeline openings` for the "
                          "neighbourhood tables.[/]")
            break
        frame = out[key]
        a = Table(title=f"{title} — top categories by mean openings_pipeline_400m")
        for col in ("category", "addresses", "mean pipeline", "median", "max",
                    "mean recent"):
            a.add_column(col)
        for r in frame.head(5).itertuples(index=False):
            a.add_row(r.category, f"{r.n_addresses:,}", f"{r.mean_pipeline_400m}",
                      f"{r.med_pipeline_400m:.0f}", f"{r.max_pipeline_400m}",
                      f"{r.mean_recent_400m}")
        console.print(a)
    console.print("[dim]Neighbourhood means are ADDRESS-WEIGHTED. Never sum a catchment "
                  "column across addresses: a filing within 400 m of N addresses is "
                  "counted N times by design.[/]")


# ---------------------------------------------------------------------------
# loci address-character -- retail- vs corporate-dominated, at address grain
# ---------------------------------------------------------------------------

address_character_app = typer.Typer(add_completion=False, help=(
    "Neighbourhood CHARACTER at address grain: is what is inside a five-minute "
    "walk retail-facing, desk-facing, industrial or residential?\n\n"
    "`build` sweeps MapPLUTO floor area (RetailArea / OfficeArea / ResArea / "
    "FactryArea / BldgArea, square feet) and LODES8 WAC jobs split into three "
    "disjoint sector groups over the SAME pedestrian walk graph, the SAME 400 m "
    "network radius and the SAME scipy Dijkstra as homes_400m and jobs_400m, and "
    "UPDATEs twelve columns on analysis.address. `stats` prints the label "
    "distribution, the share deciles the thresholds were read off, and the NTA "
    "roll-up.\n\n"
    "The shares and the label are VIEWS (analysis.address_character, "
    "analysis.nta_character), not stored columns: they are pure arithmetic on "
    "the stored numbers, so materialising them would create a second thing to "
    "keep in sync every time a threshold moves.\n\n"
    "These columns are CONTEXT beside the screen. They do NOT enter gap_score, "
    "supply_ratio_vs_base, the revenue model or any recommendation grade."))
app.add_typer(address_character_app, name="address-character")


@address_character_app.command("build")
def address_character_build(
    boroughs: str = typer.Option("MN,BK", help="Comma-separated borough codes, or ALL."),
    radius_m: float = typer.Option(400.0, "--radius-m",
                                   help="Catchment radius in NETWORK metres (default 400 = the 5-min tier)."),
    jobs_vintage: int = typer.Option(2023, "--jobs-vintage",
                                     help="LODES8 WAC vintage on disk (data/raw/lodes)."),
    dry_run: bool = typer.Option(False, "--dry-run", help="Compute and print; write nothing."),
) -> None:
    """Sweep PLUTO floor area + LODES sector jobs within 400 m of every address.

        retail_area_400m / office_area_400m / res_area_400m /
        factory_area_400m / bldg_area_400m       MapPLUTO, SQUARE FEET
        jobs_retail_400m / jobs_office_400m / jobs_other_400m
                                                 LODES8 WAC, summing to jobs_400m

    THE LOT SET IS EVERY PLUTO LOT, not analysis.address's lots. analysis.address
    is `PLUTO lots WHERE UnitsRes > 0`, so reusing it -- which is what "the exact
    lot set homes_400m uses" would have meant -- would report the Financial
    District and Industry City as ZERO office and ZERO factory floor area and
    label Midtown East residential. The catchment ENGINE is identical; only the
    weight set is widened, and filtering these lots to UnitsRes > 0 reproduces
    homes_400m's set exactly.

    UPDATE-only on analysis.address (twelve columns), pinned disjoint from the
    screen's own columns and from every sibling annotation.

    RE-APPLY AFTER EVERY SCREEN RE-RUN. `loci address-gaps` DELETEs and
    re-INSERTs analysis.address, so these twelve columns come back NULL exactly
    as every other annotation does; `character_run_at IS NULL` is the flag.

        loci address-character build --boroughs MN,BK
    """
    from loci.model import address_character as ac

    boros = _parse_boroughs(boroughs)
    con = locidb.connect(read_only=dry_run)
    if not dry_run:
        locidb.init_schema(con)
    if abs(radius_m - ac.DEFAULT_RADIUS_M) > 1e-6:
        console.print(f"[yellow]warning:[/] --radius-m {radius_m:.0f} differs from the "
                      f"{ac.DEFAULT_RADIUS_M:.0f} m the COLUMN NAMES encode; "
                      f"character_radius_m records what was actually used.")

    console.print(f"[dim]PLUTO floor area + LODES sector jobs for {','.join(boros)} at "
                  f"{radius_m:.0f} m network…[/]")
    df, report = ac.build_character(
        con, boros, radius_m=radius_m, jobs_vintage=jobs_vintage, dry_run=dry_run)

    console.print(f"MapPLUTO [bold]{report['pluto_version']}[/] · {report['lots']:,} lots in "
                  f"the scope bbox ({report['lots_residential']:,} with UnitsRes > 0 -- the "
                  f"set homes_400m uses) · {report['lot_bldg_area_total'] / 1e6:,.0f} M sq ft "
                  f"built, {report['lot_office_area_total'] / 1e6:,.0f} M office, "
                  f"{report['lot_retail_area_total'] / 1e6:,.0f} M retail")
    console.print(f"LODES WAC {report['jobs_vintage']} · {report['job_blocks']:,} blocks with "
                  f"jobs · {report['job_total_in_bbox']:,.0f} total, "
                  f"{report['job_retail_in_bbox']:,.0f} retail-facing "
                  f"({'+'.join(report['retail_sectors'])}), "
                  f"{report['job_office_in_bbox']:,.0f} desk-facing "
                  f"({'+'.join(report['office_sectors'])})")
    console.print(f"{report['addresses']:,} addresses over {report['query_nodes']:,} distinct "
                  f"graph nodes (graph {report['graph_version']})")

    tab = Table(title=f"walkable character inputs — {','.join(boros)} @ {radius_m:.0f} m network")
    for col, j in (("borough", "left"), ("addresses", "right"),
                   ("office ksf p50", "right"), ("office ksf p90", "right"),
                   ("retail ksf p50", "right"), ("factory ksf p90", "right"),
                   ("jobs retail p50", "right"), ("jobs office p90", "right")):
        tab.add_column(col, justify=j)
    for b in [*boros, "ALL"]:
        s = df if b == "ALL" else df[df["borough"] == b]
        if s.empty:
            continue
        tab.add_row(b, f"{len(s):,}",
                    f"{s['office_area_400m'].median() / 1e3:,.0f}",
                    f"{s['office_area_400m'].quantile(0.9) / 1e3:,.0f}",
                    f"{s['retail_area_400m'].median() / 1e3:,.0f}",
                    f"{s['factory_area_400m'].quantile(0.9) / 1e3:,.0f}",
                    f"{s['jobs_retail_400m'].median():,.0f}",
                    f"{s['jobs_office_400m'].quantile(0.9):,.0f}")
    console.print(tab)
    console.print("[dim]Zero is an observation ('nothing built within a five-minute walk'), "
                  "never a missing value. NEVER sum a catchment column across addresses: a "
                  "lot within 400 m of N addresses is counted N times by design.[/]")

    if dry_run:
        console.print("[dim]--dry-run:[/] nothing written.")
        raise typer.Exit(0)
    console.print(f"[green]ok[/] {report['_written']:,} rows -> analysis.address; "
                  f"analysis.address_character / analysis.nta_character refreshed")
    console.print("[dim]Now run `loci address-character stats`.[/]")


@address_character_app.command("stats")
def address_character_stats(
    boroughs: str = typer.Option("MN,BK", help="Comma-separated borough codes, or ALL."),
    top: int = typer.Option(10, "--top", help="Rows per NTA table."),
    min_addresses: int = typer.Option(200, "--min-addresses",
                                      help="Skip NTAs with fewer residential lots than this. "
                                           "Park and cemetery polygons hold a handful each and "
                                           "would otherwise take every top slot on any share."),
    deciles: bool = typer.Option(True, "--deciles/--no-deciles",
                                 help="Print the share deciles the thresholds were read off."),
) -> None:
    """Validation, label counts, share deciles and the NTA roll-up.

    The deciles are the table the thresholds have to be justified against. They
    are NOT how the thresholds were set: a cut placed at the 90th percentile of
    a share fixes the label rate at 10% BY CONSTRUCTION (D34's quantile-artefact
    lesson), so the cuts here are absolute and the deciles are what says whether
    an absolute cut lands somewhere meaningful.
    """
    import pandas as pd

    from loci.model import address_character as ac

    boros = _parse_boroughs(boroughs)
    con = locidb.connect(read_only=True)

    v = con.execute(ac.VALIDATION_SQL).fetchdf()
    t = Table(title="validation — analysis.address (ROLLUP; NULL borough = all)")
    for c in v.columns:
        t.add_column(str(c), justify="right")
    for r in v.itertuples(index=False):
        t.add_row(*[("ALL" if pd.isna(x) else f"{x:,}" if isinstance(x, (int, float)) else str(x))
                    for x in r])
    console.print(t)
    console.print("[dim]jobs_sum_mismatch counts addresses where jobs_retail + jobs_office + "
                  "jobs_other <> jobs_400m. It must be 0: the three are a partition of the "
                  "SAME LODES C000 over the SAME blocks, so a non-zero means this sweep and "
                  "`loci address-access` saw different geography (different graph, different "
                  "radius, or one of the two was never re-applied after the last "
                  "`loci address-gaps`).[/]")

    lv = con.execute(ac.LABEL_VALIDATION_SQL).fetchdf()
    t2 = Table(title="validation — analysis.address_character (labels)")
    for c in lv.columns:
        t2.add_column(str(c), justify="right")
    for r in lv.itertuples(index=False):
        t2.add_row(*[("ALL" if pd.isna(x) else f"{x:,}" if isinstance(x, (int, float)) else str(x))
                     for x in r])
    console.print(t2)

    lc = ac.label_counts(con)
    t3 = Table(title="label counts")
    for c in ("borough", "character", "addresses", "share", "mean_intensity"):
        t3.add_column(c, justify="right")
    totals = lc[lc["borough"].isna()]["addresses"].sum() if len(lc) else 0
    for b, grp in lc.groupby(lc["borough"].fillna("ALL"), sort=False):
        n = grp["addresses"].sum()
        for r in grp.itertuples(index=False):
            t3.add_row(str(b), str(r.character), f"{r.addresses:,}",
                       f"{r.addresses / n:.1%}", f"{r.mean_intensity}")
    console.print(t3)

    ov = ac.rule_overlap(con)
    console.print("[dim]rule overlap (why LABEL_ORDER is load-bearing): "
                  + " · ".join(f"{c}={int(ov[c].iloc[0]):,}" for c in ov.columns) + "[/]")

    sup = con.execute(ac.SUPPRESSION_SQL).fetchdf()
    if len(sup):
        t7 = Table(title="SUPPRESSED NTAs — label withheld (D82)")
        for c in ("borough", "nta_code", "neighborhood", "addresses", "reason"):
            t7.add_column(c, justify="right" if c == "addresses" else "left")
        for r in sup.itertuples(index=False):
            t7.add_row(str(r.borough), str(r.nta_code), str(r.neighborhood),
                       f"{r.addresses:,}", str(r.reason))
        console.print(t7)
        console.print("[dim]A suppressed address keeps every stored measure and its "
                      "retail_index; only the four-way label and its intensity are withheld, "
                      "because a share over nine addresses in Calvert Vaux Park is arithmetic "
                      "rather than geography. Suppression matches on the NTA CODE (last two "
                      "digits >= 70 = cemetery/park/airport) and never on the name — 'Park "
                      "Slope' and 'Borough Park' are real neighbourhoods.[/]")

    if deciles:
        d = ac.deciles(con, boros)
        t4 = Table(title=f"share deciles — {','.join(boros)}")
        for c in d.columns:
            t4.add_column(str(c), justify="right")
        for r in d.itertuples(index=False):
            t4.add_row(*[f"{x:.4f}" if isinstance(x, float) else str(x) for x in r])
        console.print(t4)
        console.print(f"[dim]thresholds: corporate office_area_share >= "
                      f"{ac.CORPORATE_OFFICE_AREA_SHARE} or jobs_office_share >= "
                      f"{ac.CORPORATE_JOBS_OFFICE_SHARE} with >= "
                      f"{ac.CORPORATE_JOBS_FLOOR:,} jobs; industrial factory_area_share >= "
                      f"{ac.INDUSTRIAL_FACTORY_AREA_SHARE}; retail_mixed retail_area_share >= "
                      f"{ac.RETAIL_AREA_SHARE} or (jobs_retail_share >= "
                      f"{ac.RETAIL_JOBS_SHARE} with >= {ac.RETAIL_JOBS_FLOOR:,} retail-facing "
                      f"jobs) or >= {ac.COMMERCIAL_OVERLAY_MIN_LOTS} commercially-zoned lot "
                      f"within {ac.COMMERCIAL_OVERLAY_RADIUS_M:.0f} m; else residential. "
                      f"Order: {' -> '.join(ac.LABEL_ORDER)}.[/]")

    amp = ac.am_pm_corroboration(con)
    t6 = Table(title="corroboration — AM share of subway entries by label (D76)")
    for col in amp.columns:
        t6.add_column(str(col), justify="right")
    for r in amp.itertuples(index=False):
        t6.add_row(*[("—" if pd.isna(x) else f"{x:,}" if isinstance(x, int) else str(x))
                     for x in r])
    console.print(t6)
    console.print("[dim]This is the only EXTERNAL check available. transit_am_pm_share_400m "
                  "comes from MTA turnstile entries by hour and knows nothing about PLUTO or "
                  "LODES: it is high where people LEAVE in the morning (residential catchment) "
                  "and low where they ARRIVE. If the label means anything it should fall "
                  "monotonically from residential to corporate — nothing in the label's "
                  "construction could have produced that.[/]")

    for title, order in (("most CORPORATE", "share_corporate"),
                         ("most RETAIL-MIXED", "share_retail_mixed"),
                         ("most INDUSTRIAL", "share_industrial"),
                         ("most RESIDENTIAL", "share_residential")):
        n = ac.nta_table(con, boros, order_by=order, limit=top,
                         min_addresses=min_addresses)
        # A deliberately narrow column set: the four label shares plus the two
        # corroborating numbers. The mean per-address shares stay on
        # analysis.nta_character for anyone querying it; eight columns is what
        # fits a terminal without rich squeezing every heading to one letter.
        n = n[["nta_code", "neighborhood", "addr", "dominant", "corp", "retail",
               "indus", "resid", "jobs_p50", "am_pm"]].copy()
        n["neighborhood"] = n["neighborhood"].str.slice(0, 24)
        t5 = Table(title=f"NTAs — {title} ({','.join(boros)}, address-weighted)")
        for col in n.columns:
            t5.add_column(str(col), justify="left" if col in ("nta_code", "neighborhood",
                                                              "dominant") else "right")
        for r in n.itertuples(index=False):
            t5.add_row(*[("—" if pd.isna(x) else f"{x:,}" if isinstance(x, int)
                          else str(x)) for x in r])
        console.print(t5)

    console.print("[dim]NTA means are ADDRESS-WEIGHTED over RESIDENTIAL lots, so they read "
                  "'what the average resident's five-minute walk contains', not 'what the "
                  "average acre contains'. In an NTA with a big non-residential district and "
                  "a small residential pocket (the Sunset Park waterfront, the FiDi fringe) "
                  "those are very different numbers. am_pm is the D76 morning share of subway "
                  "ENTRIES -- high where people LEAVE in the morning (residential catchment), "
                  "low where they ARRIVE -- and rests on n_am_pm addresses, not all of "
                  "them.[/]")


# ===========================================================================
# address-legality -- commercial LEGALITY at address grain (D82, seed 2026-09-14)
# ===========================================================================
address_legality_app = typer.Typer(add_completion=False, help=(
    "Commercial legality at address grain: is a storefront here allowed, or "
    "only tolerated?\n\n"
    "`build` joins MapPLUTO's zonedist1/overlay1/overlay2/landuse/ownertype/"
    "histdist/landmark onto analysis.address by BBL (read straight off the "
    "CSV, never into Python memory) and stamps legality_run_at. `stats` "
    "prints the null rate and the legality distribution off the derived view "
    "analysis.address_legality (commercial | grandfathered | ineligible).\n\n"
    "RE-APPLY AFTER `loci address-gaps`, same contract as address-character: "
    "the DELETE-then-INSERT rebuild nulls these seven columns out.\n\n"
    "Zoning is a LABEL and a FILTER ON RECOMMENDATION OUTPUTS ONLY (D82). It "
    "enters no score, no grade, no gap_score, no supply_ratio."))
app.add_typer(address_legality_app, name="address-legality")


@address_legality_app.command("build")
def address_legality_build(
    dry_run: bool = typer.Option(False, "--dry-run", help="Report only; write nothing."),
) -> None:
    """Populate the seven PLUTO columns on analysis.address by BBL join, then
    print the null rate and the legality distribution.

        loci address-legality build
    """
    from loci.model import address_legality as al

    con = _connect_retrying(read_only=dry_run)
    if not dry_run:
        locidb.init_schema(con)
    report = al.build_legality_columns(con, dry_run=dry_run)
    console.print(f"[dim]MapPLUTO CSV: {report['pluto_csv']}[/]")
    console.print(f"addresses with a bbl: [bold]{report['with_bbl']:,}[/] · "
                  f"missing zonedist1: {report['null_zonedist1']:,} "
                  f"({report['null_rate'] * 100:.2f}%)")
    if report["null_rate"] > 0.01:
        console.print("[yellow]warning:[/] null rate over addresses with a bbl "
                      "exceeds the 1% budget (AC-1).")
    if dry_run:
        console.print("[dim]--dry-run:[/] nothing written.")
        raise typer.Exit(0)

    dist = al.legality_distribution(con)
    tab = Table(title="analysis.address_legality — legality distribution")
    tab.add_column("legality", justify="left")
    tab.add_column("addresses", justify="right")
    for k in al.LEGALITY_VALUES:
        tab.add_row(k, f"{dist.get(k, 0):,}")
    console.print(tab)
    console.print("[green]ok[/] analysis.address seven PLUTO columns refreshed; "
                  "analysis.address_legality reflects the current poi_supply_status.")


@address_legality_app.command("stats")
def address_legality_stats() -> None:
    """Print the legality distribution and the top ineligible bases, read-only.

        loci address-legality stats
    """
    from loci.model import address_legality as al
    from loci.model.recommend import connect_read_only

    con = connect_read_only()
    # D97 item 7: a green suite (or a quiet CLI run) must never hide an
    # unapplied build layer. If analysis.address holds rows but every one has
    # a NULL legality, the sql/031 columns exist but `address-legality build`
    # has simply never populated them (or ran before a rule change) -- fail
    # loud rather than print a distribution that is all zeros.
    total_addr, populated = con.execute(
        "SELECT count(*), count(*) FILTER (WHERE legality IS NOT NULL) "
        "FROM analysis.address").fetchone()
    if total_addr and not populated:
        console.print(
            "[red]error:[/] analysis.address.legality is entirely NULL — "
            "`loci address-legality build` has not been run against this "
            "warehouse (or it predates a rule change). Re-apply with:\n"
            "    loci address-legality build")
        raise typer.Exit(1)

    dist = al.legality_distribution(con)
    tab = Table(title="analysis.address_legality — legality distribution")
    tab.add_column("legality", justify="left")
    tab.add_column("addresses", justify="right")
    total = sum(dist.values()) or 1
    for k in al.LEGALITY_VALUES:
        tab.add_row(k, f"{dist.get(k, 0):,} ({dist.get(k, 0) / total * 100:.1f}%)")
    console.print(tab)

    basis = con.execute(
        "SELECT legality_basis, count(*) AS n FROM analysis.address_legality "
        "WHERE legality = 'ineligible' GROUP BY 1 ORDER BY n DESC LIMIT 10"
    ).fetchall()
    if basis:
        t2 = Table(title="top ineligible bases")
        t2.add_column("legality_basis", justify="left")
        t2.add_column("n", justify="right")
        for b, n in basis:
            t2.add_row(b, f"{n:,}")
        console.print(t2)
    console.print("[dim]D82: legality is a card label and a recommendation filter only. "
                  "histdist / landmark never affect it.[/]")


# ===========================================================================
# sidewalk-count -- counting people in public traffic-camera frames (D85)
# ===========================================================================
sidewalk_app = typer.Typer(add_completion=False, help=(
    "Count the people in NYC DOT traffic-camera frames.\n\n"
    "PERSONS VISIBLE IN ONE FRAME -- a STOCK, not a FLOW. The DOT bi-annual "
    "hand count is a flow (people per hour past a screenline); this is a stock "
    "(people standing in a cone of view at an instant). Little's law is the "
    "only bridge and nothing here measures dwell, so `validate` reports a RANK "
    "correlation and refuses to emit a conversion factor.\n\n"
    "The imagery is public and COUNT-ONLY: frames are never stored unless "
    "--keep-frames, and then only under data/frames/ for QA."))
app.add_typer(sidewalk_app, name="sidewalk-count")


def _sidewalk_resolve(con, camera: str | None, near: str | None, radius_m: float):
    """--camera id | --near 'lat,lon' -> one Camera, printing the alternatives."""
    from loci.model import sidewalk_count as sw

    if bool(camera) == bool(near):
        raise typer.BadParameter("pass exactly one of --camera or --near")
    if camera:
        return sw.get_camera(con, camera)
    try:
        lat, lon = (float(x) for x in near.replace(" ", "").split(","))
    except ValueError:
        raise typer.BadParameter(f"--near {near!r} is not 'lat,lon'") from None
    found = sw.cameras_near(con, lat=lat, lon=lon, radius_m=radius_m)
    if not found:
        raise typer.BadParameter(
            f"no camera within {radius_m:.0f} m of {lat},{lon}. The registry holds "
            f"969 cameras citywide, so an empty result usually means the point is "
            f"off an arterial rather than that the feed is down.")
    t = Table(title=f"cameras within {radius_m:.0f} m of {lat},{lon}")
    for c, j in (("camera_id", "left"), ("name", "left"), ("borough", "left"),
                 ("dist_m", "right")):
        t.add_column(c, justify=j)
    for c in found[:10]:
        t.add_row(c.camera_id, c.name, c.borough or "—", f"{c.dist_m:.0f}")
    console.print(t)
    console.print(f"[dim]using the nearest: {found[0].camera_id}[/]")
    return found[0]


@sidewalk_app.command("sample")
def sidewalk_sample(
    camera: str = typer.Option(None, "--camera", help="staging.dot_camera.camera_id"),
    near: str = typer.Option(None, "--near", help="'lat,lon'; uses the nearest camera"),
    radius_m: float = typer.Option(300.0, "--radius-m", help="search radius for --near"),
    minutes: float = typer.Option(10.0, "--minutes", help="how long to sample"),
    interval_s: float = typer.Option(10.0, "--interval-s", help="seconds between fetches"),
    dry_run: bool = typer.Option(False, "--dry-run",
                                 help="print the plan, fetch ONE frame, write nothing"),
    keep_frames: bool = typer.Option(False, "--keep-frames",
                                     help="also write the JPEGs to data/frames/<camera>/"),
) -> None:
    """Fetch a camera every S seconds for N minutes and count the people.

    The warehouse lock is held for the camera lookup and again for one INSERT
    at the end -- never for the length of the run, because another session
    rebuilding the database mid-sample is normal here (D69).
    """
    from loci.model import sidewalk_count as sw

    con = _connect_retrying(read_only=True)
    try:
        cam = _sidewalk_resolve(con, camera, near, radius_m)
    finally:
        con.close()

    plan = sw.plan_run(cam, minutes, interval_s)
    console.print(f"[bold]{plan.describe()}[/]")
    console.print(f"[dim]budget: MAX_FRAMES_PER_RUN={sw.MAX_FRAMES_PER_RUN}, "
                  f"politeness floor {sw.MIN_INTERVAL_S:g}s. Counts only; frames are "
                  f"{'KEPT under data/frames/ for QA' if keep_frames else 'discarded'}.[/]")

    out = sw.sample(cam, minutes, interval_s, dry_run=dry_run, keep_frames=keep_frames)
    rep = out["report"]
    console.print(f"fetched [bold]{rep['fetched']}[/] · unique [bold]{rep['unique']}[/] · "
                  f"duplicate {rep['duplicate_rate']:.0%} · errors {rep['errors']} · "
                  f"{rep['mean_bytes'] / 1024:.0f} KB/frame · "
                  f"{rep['seconds_per_frame'] * 1000:.0f} ms/frame "
                  f"({rep['model']} {rep['model_version']}, quality {rep['model_quality']})")
    if rep["unique"]:
        counts = sorted(r["n_persons"] for r in out["rows"])
        mid = counts[len(counts) // 2]
        console.print(f"persons/frame: mean [bold]{rep['mean_persons']:.2f}[/] · "
                      f"p50 {mid} · max {rep['max_persons']}")

    if dry_run:
        console.print("[dim]--dry-run:[/] one frame fetched, nothing written.")
        raise typer.Exit(0)

    con = _connect_retrying(read_only=False)
    try:
        con.execute((locidb.SQL_DIR / "024_sidewalk_count.sql").read_text())
        n = sw.write_rows(con, out["rows"])
    finally:
        con.close()
    console.print(f"[green]ok[/] {n:,} new rows -> analysis.sidewalk_count "
                  f"({rep['unique'] - n} already stored)")
    console.print("[dim]persons IN FRAME, not pedestrians per hour. Field of view "
                  "differs by camera, so compare a camera with ITSELF across time "
                  "before comparing two cameras with each other.[/]")


@sidewalk_app.command("schedule")
def sidewalk_schedule(
    camera: str = typer.Option(..., "--camera", help="staging.dot_camera.camera_id"),
    days: int = typer.Option(14, "--days", help="how many days the plan covers"),
    interval_s: float = typer.Option(10.0, "--interval-s"),
    minutes: float = typer.Option(10.0, "--minutes", help="minutes per daypart block"),
) -> None:
    """Emit the launchd-friendly sampling plan. RUNS NOTHING, WRITES NOTHING."""
    from loci.model import sidewalk_count as sw

    con = _connect_retrying(read_only=True)
    try:
        cam = sw.get_camera(con, camera)
    finally:
        con.close()

    plan = sw.schedule_plan(cam, days=days, interval_s=interval_s,
                            minutes_per_daypart=minutes)
    t = Table(title=f"{cam.name} ({cam.camera_id}) — {days}-day plan")
    for c in plan.columns:
        t.add_column(str(c), justify="right" if plan[c].dtype.kind in "if" else "left")
    for r in plan.itertuples(index=False):
        t.add_row(*[f"{x:,}" if isinstance(x, int) else
                    (f"{x:g}" if isinstance(x, float) else str(x)) for x in r])
    console.print(t)
    total = int(plan["frames_total"].sum())
    console.print(f"[bold]{len(plan)}[/] blocks per cycle · "
                  f"[bold]{total:,}[/] frames over {days} days · "
                  f"~{total * 0.11 / 60:.0f} min of CPU at 0.11 s/frame")
    console.print("[dim]launch_local is the MIDPOINT of each daypart, not its edge: a "
                  "block starting at 06:00 sharp measures the quietest ten minutes of "
                  "am_peak and calls it the peak. Each block is a separate "
                  "`loci sidewalk-count sample --camera … --minutes … ` invocation, "
                  "sized to sit inside MAX_FRAMES_PER_RUN.[/]")


@sidewalk_app.command("stats")
def sidewalk_stats(
    camera: str = typer.Option(None, "--camera", help="one camera; default all"),
) -> None:
    """Per camera x day_type x daypart: N frames, mean / p50 / max persons."""
    from loci.model import sidewalk_count as sw

    con = _connect_retrying(read_only=True)
    try:
        df = sw.stats(con, camera_id=camera)
    finally:
        con.close()
    if not len(df):
        console.print("[yellow]analysis.sidewalk_count is empty[/] — nothing sampled yet. "
                      "`loci sidewalk-count sample --near \"40.71,-73.95\" --minutes 10`")
        raise typer.Exit(0)
    df = df.copy()
    df["camera"] = df["camera"].astype(str).str.slice(0, 28)
    t = Table(title="persons per FRAME (a stock, not a flow)")
    for c in df.columns:
        t.add_column(str(c), justify="left" if c in ("camera_id", "camera", "day_type",
                                                     "daypart") else "right")
    for r in df.itertuples(index=False):
        t.add_row(*[f"{x:.2f}" if isinstance(x, float) else str(x) for x in r])
    console.print(t)
    console.print("[dim]mean and p50 are both here because a count that is zero most of "
                  "the time and eleven once has a mean that describes no moment of the "
                  "day. Where they disagree, the reading rests on a handful of frames.[/]")


@sidewalk_app.command("validate")
def sidewalk_validate(
    radius_m: float = typer.Option(None, "--radius-m",
                                   help="camera-to-count-point match radius"),
    round_: str = typer.Option(None, "--round",
                               help="DOT round as YYYY-MM, e.g. 2026-05; default latest"),
    out: Path = typer.Option(None, "--out", help="write the matched pairs to this CSV"),
) -> None:
    """Camera persons-per-frame vs the DOT bi-annual hand count, co-located.

    READ-ONLY. Only cameras that have actually been sampled can appear, so N is
    printed at every level and an empty intersection is a stated outcome, not
    an error.
    """
    from loci.model import sidewalk_count as sw

    r = radius_m if radius_m is not None else sw.VALIDATE_RADIUS_M
    con = _connect_retrying(read_only=True)
    try:
        pairs, rep = sw.validate(con, radius_m=r, round_=round_)
    finally:
        con.close()

    console.print(f"round [bold]{rep['round']}[/] · match radius {rep['radius_m']:.0f} m · "
                  f"{rep['cameras_in_radius']} cameras sit within it of "
                  f"{rep['points_in_radius']} count points "
                  f"({rep['pairs_in_radius']} camera x window pairs)")
    console.print(f"cameras sampled so far: [bold]{rep['cameras_sampled']}[/] · "
                  f"compared here: [bold]{rep['cameras_compared']}[/] · "
                  f"matched observations N = [bold]{rep['n']}[/]")
    if rep.get("note"):
        console.print(f"[yellow]{rep['note']}[/]")
    if rep["spearman_rho"] is not None:
        console.print(f"Spearman rho, camera mean persons/frame vs DOT people per "
                      f"COUNTED HOUR: [bold]{rep['spearman_rho']:+.3f}[/] "
                      f"(vs the raw window count: "
                      f"{rep['spearman_rho_raw_count']:+.3f})")
        console.print("[dim]the per-hour rho is the headline because DOT's pm window is "
                      "THREE hours and am/md are two — ranking the raw counts would "
                      "reward pm for the protocol, not for the sidewalk.[/]")
    if len(pairs):
        t = Table(title="matched (camera, DOT window) observations")
        cols = ["camera", "point_id", "period", "dist_m", "frames",
                "mean_persons", "p50_persons", "max_persons", "dot_count",
                "dot_per_hour"]
        for c in cols:
            t.add_column(c, justify="left" if c in ("camera", "point_id", "period")
                         else "right")
        for row in pairs.itertuples(index=False):
            d = row._asdict()
            t.add_row(str(d["camera"])[:24], str(d["point_id"]), str(d["period"]),
                      f"{d['dist_m']:.0f}", str(int(d["frames"])),
                      f"{d['mean_persons']:.2f}", f"{d['p50_persons']:.1f}",
                      str(int(d["max_persons"])), f"{int(d['dot_count']):,}",
                      f"{d['dot_per_hour']:,.0f}")
        console.print(t)
    console.print("[dim]A RANK correlation and nothing else. The two sides are different "
                  "physical quantities — a stock and a flow — so any ratio between them "
                  "would be a dwell time estimated from one number. What a positive rho "
                  "supports is narrow: that the camera orders the three windows of a day, "
                  "and orders co-located places, the way a hand count does. The DOT count "
                  "is also a WEEKDAY count from a single day in the round, so weekend "
                  "frames are excluded here and weather is not averaged out on either "
                  "side.[/]")


# ===========================================================================
# NYC DOT -- the bi-annual pedestrian counts and the traffic cameras.
#
# Owner, 2026-09-13: "we need NYC DOT data, both the bi-annual and the camera
# data."
#
#   loci dot-counts ingest            staging.dot_pedestrian_count (long form,
#                                     every round since 2007)
#   loci dot-counts stats             points, rounds, latest AM/MD/PM per point,
#                                     ten-year trend
#   loci dot-counts address-context   nearest count point + nearest camera on
#                                     every address (UPDATE-only)
#   loci dot-cameras ingest           staging.dot_camera (the sampler's registry)
#   loci dot-cameras probe            re-verify the image endpoint: no auth,
#                                     and does the frame actually change?
#   loci dot-export                   webmap/data/dot.json
#
# This block is appended at the END of the file on purpose: another session is
# editing cli.py above it, and an append never conflicts with an edit.
# ===========================================================================

DOT_DISTANCE_CAVEAT = (
    "dot_point_m and camera_m are STRAIGHT-LINE metres (Euclidean in EPSG:32618), "
    "unlike homes_400m / transit_entries_400m / jobs_400m, which are NETWORK "
    "metres on the pedestrian walk graph. A straight line is a LOWER BOUND on the "
    "walk — across a rail cut, a canal or a highway the walk can be several times "
    "this. Never compare the two."
)


def _dot_connect(read_only: bool = False, attempts: int = 12,
                 path: str | None = None):
    """Open the warehouse, retrying while another build holds the write lock.

    A concurrent `loci address-gaps` or `loci export-webmap` can hold DuckDB's
    single-writer lock for minutes. Failing instantly on that is worse than
    waiting: the operator re-runs by hand and the run is lost either way.
    Backs off 5 s, 10 s, ... capped at 30 s, then RAISES rather than silently
    proceeding without a database.
    """
    import time as _time

    import duckdb as _duckdb

    last = None
    for i in range(attempts):
        try:
            return locidb.connect(path, read_only=read_only)
        except (_duckdb.IOException, _duckdb.Error) as exc:   # lock, or a
            # transient open failure. Re-raise anything that is not a lock.
            if "lock" not in str(exc).lower():
                raise
            last = exc
            wait = min(5 * (i + 1), 30)
            console.print(f"[yellow]database locked[/] (attempt {i + 1}/{attempts}); "
                          f"retrying in {wait}s")
            _time.sleep(wait)
    raise RuntimeError(f"could not obtain the DuckDB lock after {attempts} "
                       f"attempts: {last}")


def _dot_migrate(con) -> None:
    """Apply sql/022_dot.sql ONLY — not the whole migration sweep.

    `locidb.init_schema` replays every migration and re-CREATEs the generated
    views (analysis.address_gaps, analysis.address_character). That is right
    for `loci init-db` and wrong for a source ingest running beside another
    build: rebuilding a dozen views to add two staging tables is a large
    blast radius for no gain. 022 is CREATE TABLE IF NOT EXISTS + ADD COLUMN
    IF NOT EXISTS throughout, so this is idempotent and touches nothing else.

    On a database that has no analysis.address yet (a fresh clone) there is
    nothing to ALTER and the full sweep is the right answer, so it falls back.
    """
    has_address = con.execute(
        "SELECT count(*) FROM information_schema.tables "
        "WHERE table_schema = 'analysis' AND table_name = 'address'").fetchone()[0]
    if not has_address:
        locidb.init_schema(con)
        return
    con.execute((locidb.SQL_DIR / "022_dot.sql").read_text())


dot_counts_app = typer.Typer(add_completion=False, help=(
    "NYC DOT Bi-Annual Pedestrian Counts (cqsj-cfgu) — the only DIRECT "
    "observation of sidewalk volume this project has.\n\n"
    "114 screenlines, counted BY HAND in three windows (AM 07-09, MD 12-14, "
    "PM 16-19 — note PM is three hours and the others are two), twice a year "
    "since 2007. `ingest` writes the whole history long-form into "
    "staging.dot_pedestrian_count: the feed is WIDE (three new columns per "
    "round, named inconsistently — 'may_07_am', 'may_22_p_m', 'oct24_md', "
    "'may26_pm') and the column names are PARSED, never typed.\n\n"
    "NOT A SAMPLE OF THE CITY and never an input to a score. DOT picked these "
    "points for traffic engineering, on busy commercial corridors and bridges, "
    "so the bottom of the volume range is barely represented. It is context, "
    "and it is the external check the walkable-demand measures are validated "
    "against (`loci validate-demand`)."))
app.add_typer(dot_counts_app, name="dot-counts")

dot_cameras_app = typer.Typer(add_completion=False, help=(
    "NYC DOT traffic cameras (NYCTMC) — the camera REGISTRY, not the frames.\n\n"
    "`ingest` writes staging.dot_camera: one row per public camera with a "
    "fetchable image URL. This is the contract the frame sampler builds "
    "against; per-frame observations are camera × timestamp and belong in "
    "their own table, never as columns here.\n\n"
    "The siting IS the bias: signalised intersections on arterials, 376 in "
    "Manhattan against 81 in the Bronx, no published bearing or field of view. "
    "A person count from a frame is a count on an unknown catchment."))
app.add_typer(dot_cameras_app, name="dot-cameras")


@dot_counts_app.command("ingest")
def dot_counts_ingest(
    refresh: bool = typer.Option(False, "--refresh",
                                 help="Re-pull the feed instead of reading data/raw/."),
    dry_run: bool = typer.Option(False, "--dry-run", help="Parse and print; write nothing."),
) -> None:
    """Pull cqsj-cfgu and write every (point × round × period) row.

    Idempotent: DELETE-then-INSERT of the whole table, because the feed
    republishes the entire history on every release and 12k rows do not earn an
    incremental path.

    NULL cells produce NO ROW (Socrata omits them; a point added in 2020 has no
    2007 row). ZERO counts DO produce rows — twelve exist and they are
    observations of an empty screenline, not gaps.
    """
    from loci.sources.cities.nyc import dot_pedestrian as dp

    con = _dot_connect()
    _dot_migrate(con)
    _, rep = dp.ingest(con, refresh=refresh, dry_run=dry_run)

    t = Table(title="DOT bi-annual pedestrian counts — ingest")
    t.add_column("metric"); t.add_column("value", justify="right")
    for k in ("rows_in_feed", "points", "on_street_points", "bridge_points",
              "n_rounds", "first_round", "last_round", "cells_possible",
              "cells_present", "cells_absent_or_null", "zero_counts",
              "total_count", "dropped_rows_without_geometry", "written"):
        v = rep.get(k)
        t.add_row(k, f"{v:,}" if isinstance(v, int) else str(v))
    console.print(t)
    console.print(f"[dim]rounds parsed: {', '.join(rep['rounds'])}[/]")
    console.print("[dim]cells_possible = points × rounds × 3. The difference "
                  "between it and cells_present is rounds a point was not in "
                  "the programme for, NOT zeros — Socrata omits a null cell and "
                  "a zero is stored as a zero.[/]")
    if dry_run:
        console.print("[yellow]--dry-run: nothing written[/]")


@dot_counts_app.command("stats")
def dot_counts_stats(
    top: int = typer.Option(10, help="How many points to print, by latest whole-round count."),
    trend_years: int = typer.Option(10, "--trend-years",
                                    help="Window for the per-point slope, in years."),
    bridges: bool = typer.Option(False, "--bridges/--no-bridges",
                                 help="Include the 14 bridge-midpoint points."),
) -> None:
    """Points, rounds, each point's latest AM/MD/PM, and its ten-year trend.

    The trend is the OLS slope of the WHOLE-ROUND total (AM+MD+PM = the round's
    seven counted hours) against DECIMAL YEARS, in people per year, fitted over
    the last `--trend-years` years anchored on the feed's latest round — the
    same calendar window for every point, so the column is comparable across
    points. Decimal years and not round number: the rounds are not evenly
    spaced (no September 2019, no May 2020, and 2024's spring round is June), so
    counting rounds would treat a 17-month gap as one step.

    A slope on fewer than three rounds is NULL. It is a description of a noisy
    series — two hours on one day, twice a year — not a forecast and not a test.
    """
    from loci.sources.cities.nyc import dot_pedestrian as dp

    con = _dot_connect(read_only=True)
    summary = dp.table_summary(con)
    df = dp.point_summary(con, trend_years=trend_years)
    if not bridges:
        df = df[~df["is_bridge"].astype(bool)]

    t = Table(title="staging.dot_pedestrian_count")
    t.add_column("metric"); t.add_column("value", justify="right")
    for k in ("rows", "points", "on_street_points", "bridge_points", "rounds",
              "first_round", "last_round", "zero_counts", "total_count"):
        v = summary[k]
        t.add_row(k, f"{v:,}" if isinstance(v, int) else str(v))
    console.print(t)

    rounds = con.execute(
        "SELECT round, COUNT(DISTINCT point_id) AS points, SUM(count) AS total "
        "FROM staging.dot_pedestrian_count GROUP BY round ORDER BY round").fetchdf()
    tr = Table(title="rounds")
    for col in ("round", "points", "total"):
        tr.add_column(col, justify="left" if col == "round" else "right")
    for r in rounds.itertuples(index=False):
        tr.add_row(r.round, f"{int(r.points):,}", f"{int(r.total):,}")
    console.print(tr)

    head = df.head(top)
    tp = Table(title=f"top {len(head)} points by latest whole-round count"
                     f"{'' if bridges else ' (on-street only)'}")
    for col, just in (("loc", "right"), ("borough", "left"), ("street", "left"),
                      ("from", "left"), ("round", "left"), ("am", "right"),
                      ("md", "right"), ("pm", "right"), ("total", "right"),
                      (f"trend/yr ({trend_years}y)", "right"), ("N", "right")):
        tp.add_column(col, justify=just)
    for r in head.itertuples(index=False):
        trend = "—" if r.trend_per_year is None or r.trend_per_year != r.trend_per_year \
            else f"{r.trend_per_year:+,.0f}"
        tp.add_row(str(int(r.point_id)), str(r.borough or "—"),
                   str(r.street or "—")[:22], str(r.from_street or "—")[:20],
                   str(r.latest_round or "—"),
                   *[f"{int(v):,}" if v == v and v is not None else "—"
                     for v in (r.latest_am, r.latest_md, r.latest_pm, r.latest_total)],
                   trend,
                   "—" if r.trend_n_rounds != r.trend_n_rounds else str(int(r.trend_n_rounds)))
    console.print(tp)
    console.print("[dim]AM 07:00-09:00 (2h), MD 12:00-14:00 (2h), PM 16:00-19:00 "
                  "(3h). The three windows are NOT equal-length and must never be "
                  "averaged as though they were; `total` is people observed in the "
                  "round's seven counted hours and is NOT a daily volume — DOT "
                  "publishes no expansion factor. These 114 points are DOT's "
                  "traffic-engineering geography, not a sample of New York.[/]")


@dot_counts_app.command("address-context")
def dot_counts_address_context(
    boroughs: str = typer.Option("MN,BK", help="Comma-separated borough codes, or ALL."),
    include_bridges: bool = typer.Option(False, "--include-bridges",
                                         help="Let bridge midpoints be a nearest count point."),
    db: str = typer.Option(None, "--db",
                           help="Warehouse path (default data/loci.duckdb). Point it at a "
                                "snapshot copy to prove a run without touching the live DB."),
    dry_run: bool = typer.Option(False, "--dry-run", help="Compute and print; write nothing."),
) -> None:
    """Nearest DOT count point and nearest camera, on every address.

        dot_point_id / dot_point_m            nearest ON-STREET count point
        dot_latest_round / _am / _md / _pm    that point's latest COMPLETE round
        camera_id / camera_m                  nearest NYCTMC camera
        dot_context_run_at                    NULL = never run for this row

    STRAIGHT-LINE distance, Euclidean in EPSG:32618, which is the one place in
    this project where a distance is not a network distance. It is a LOWER
    BOUND on the walk. 114 points and 969 cameras do not justify a second
    40-minute Dijkstra, and "which observation is nearest" has a defensible
    straight-line answer where "how many homes can walk here" does not.

    "Latest round" is PER POINT, not global: points enter and leave the
    programme, and using the feed's latest round would write NULL counts at a
    point that simply was not counted in May 2026 — indistinguishable from a
    quiet street.

    UPDATE-only on analysis.address, RESET-then-UPDATE in scope, pinned
    disjoint from the screen's own columns and every sibling annotation.
    CONTEXT, never a filter: nothing here enters gap_score, supply_ratio or a
    grade. Re-apply after every `loci address-gaps` run, which DELETEs the rows
    these columns live on.
    """
    from loci.model import address_dot_context as adc

    boros = None if boroughs.strip().upper() == "ALL" else \
        [b.strip().upper() for b in boroughs.split(",") if b.strip()]
    con = _dot_connect(path=db)
    _dot_migrate(con)
    _, rep = adc.build_context(con, boros, include_bridges=include_bridges,
                               dry_run=dry_run)

    t = Table(title="analysis.address — DOT context")
    t.add_column("metric"); t.add_column("value", justify="right")
    for k in ("boroughs", "count_points", "count_points_with_complete_latest_round",
              "cameras", "addresses", "metric_crs", "include_bridges", "_written"):
        v = rep.get(k)
        t.add_row(k, f"{v:,}" if isinstance(v, int) else str(v))
    t.add_row("dot_point_m p50", f"{rep['dot_point_m_p50']:,.0f} m")
    t.add_row("camera_m p50", f"{rep['camera_m_p50']:,.0f} m")
    t.add_row("within 400 m of a camera", f"{rep['within_400m_of_camera']:.1%}")
    t.add_row("within 400 m of a count point", f"{rep['within_400m_of_count_point']:.1%}")
    console.print(t)

    tb = Table(title="by borough")
    for col in ("borough", "addresses", "dot_m p50", "dot_m p90", "cam_m p50",
                "cam_m p90", "≤400 m camera", "≤400 m count pt"):
        tb.add_column(col, justify="left" if col == "borough" else "right")
    for boro, d in sorted(rep["by_borough"].items()):
        tb.add_row(boro, f"{d['addresses']:,}", f"{d['dot_point_m_p50']:,.0f}",
                   f"{d['dot_point_m_p90']:,.0f}", f"{d['camera_m_p50']:,.0f}",
                   f"{d['camera_m_p90']:,.0f}",
                   f"{d['within_400m_of_camera']:.1%}",
                   f"{d['within_400m_of_count_point']:.1%}")
    console.print(tb)
    console.print(f"[dim]{DOT_DISTANCE_CAVEAT}[/]")
    console.print("[dim]A camera's coordinates are the POLE, not the view: no "
                  "bearing, field of view or height is published, so camera_m = 60 "
                  "does not mean the address is in frame. And the camera gradient "
                  "is DOT's operational one (arterial intersections), so 'share "
                  "within 400 m of a camera' is a statement about arterial "
                  "proximity, never about footfall or exposure.[/]")
    if dry_run:
        console.print("[yellow]--dry-run: nothing written[/]")


@dot_cameras_app.command("ingest")
def dot_cameras_ingest(
    refresh: bool = typer.Option(False, "--refresh",
                                 help="Re-pull the feed instead of reading data/raw/."),
    dry_run: bool = typer.Option(False, "--dry-run", help="Fetch and print; write nothing."),
) -> None:
    """Pull the NYCTMC camera list into staging.dot_camera.

    One row per camera: camera_id, name, lon, lat, image_url, is_online, area,
    borough, fetched_at. Whole-table DELETE-then-INSERT — the feed is a full
    snapshot with no vintage and no changelog, so an incremental merge would
    have to invent a retirement rule.

    `is_online` is parsed from the feed's STRING 'true' (bool('false') is True,
    which is exactly the bug this avoids). It read true on 969 of 969 cameras at
    verification, which is not a plausible steady state for 969 outdoor cameras:
    treat it as "published", not "returning frames", and never filter a universe
    on it.
    """
    from loci.sources.cities.nyc import dot_cameras as dc

    con = _dot_connect()
    _dot_migrate(con)
    _, rep = dc.ingest(con, refresh=refresh, dry_run=dry_run)

    t = Table(title="staging.dot_camera — ingest")
    t.add_column("metric"); t.add_column("value", justify="right")
    for k in ("rows_in_feed", "cameras", "online", "offline", "online_unknown",
              "dropped_without_id", "dropped_without_geometry",
              "dropped_outside_nyc", "fetched_at", "written"):
        v = rep.get(k)
        t.add_row(k, f"{v:,}" if isinstance(v, int) else str(v))
    for boro, n in rep["by_borough"].items():
        t.add_row(f"  {boro}", f"{n:,}")
    console.print(t)
    if rep["unknown_areas"]:
        console.print(f"[yellow]unmapped `area` values (borough left NULL, never "
                      f"guessed): {rep['unknown_areas']}[/]")
    console.print("[dim]The siting IS the bias: signalised intersections on "
                  "arterials, chosen to watch vehicle queues. No bearing, field of "
                  "view, height or lens is published, so what any camera sees is "
                  "an unknown catchment — two cameras 20 m apart can watch "
                  "disjoint sidewalks.[/]")
    if dry_run:
        console.print("[yellow]--dry-run: nothing written[/]")


@dot_cameras_app.command("probe")
def dot_cameras_probe(
    camera_id: str = typer.Option(None, help="Camera to probe (default: the first in the registry)."),
    gap_s: float = typer.Option(5.0, "--gap-s", help="Seconds between the two fetches."),
) -> None:
    """Fetch one camera's frame twice and report whether the bytes changed.

    This is the check that established the sampler's contract — no auth, 200
    image/jpeg, Cache-Control: no-store, no Last-Modified, and a different
    payload on every request. It is a command rather than a note so the claim
    can be RE-VERIFIED when the sampler misbehaves instead of being believed.
    Stores no image and writes nothing.
    """
    from loci.sources.cities.nyc import dot_cameras as dc

    url = None
    if camera_id is None:
        con = _dot_connect(read_only=True)
        row = con.execute("SELECT camera_id, image_url FROM staging.dot_camera "
                          "ORDER BY camera_id LIMIT 1").fetchone()
        if not row:
            raise typer.BadParameter(
                "staging.dot_camera is empty — run `loci dot-cameras ingest` "
                "or pass --camera-id.")
        camera_id, url = row
    rep = dc.probe_image(camera_id, url, gap_s=gap_s)

    t = Table(title=f"camera {camera_id} — image endpoint")
    for col in ("shot", "status", "content-type", "bytes", "sha1",
                "cache-control", "last-modified"):
        t.add_column(col, justify="left")
    for i, s in enumerate(rep["shots"]):
        t.add_row(f"t+{0 if i == 0 else gap_s:g}s", str(s["status"]),
                  str(s["content_type"]), f"{s['bytes']:,}", s["sha1"],
                  str(s["cache_control"]), str(s["last_modified"] or "—"))
    console.print(t)
    console.print(f"[{'green' if rep['changed'] else 'yellow'}]"
                  f"frame {'CHANGED' if rep['changed'] else 'IDENTICAL'} across "
                  f"{gap_s:g}s[/] — no auth required: {not rep['auth_required']}")
    console.print("[dim]No Last-Modified and no ETag means the response cannot "
                  "tell you how stale a frame is. The sampler's own fetch time is "
                  "the only timestamp of record.[/]")


@app.command(name="dot-export")
def dot_export_cmd(
    out_dir: str = typer.Option(None, "--out-dir",
                                help="Directory for dot.json (default webmap/data)."),
    trend_years: int = typer.Option(10, "--trend-years", help="Trend window, in years."),
) -> None:
    """Write webmap/data/dot.json — the count points and cameras as a layer.

    A STANDALONE file with a standalone command: viz/webmap_export.py and
    webmap/index.html are owned by another thread, so nothing there is touched.
    Wiring the layer in later is a fetch of `data/dot.json` plus a toggle.

    The file carries its own `caveats` block, meant to be rendered UNTRUNCATED
    wherever the layers are switched on — 969 camera dots look like coverage and
    are not.
    """
    from loci.viz import dot_export as de

    con = _dot_connect(read_only=True)
    rep = de.export(con, out_dir=out_dir, trend_years=trend_years)
    console.print(f"[green]ok[/] {rep['path']} — {rep['counts']} count points, "
                  f"{rep['cameras']} cameras, {rep['bytes']:,} bytes")


@app.command(name="gen-paid-sources")
def gen_paid_sources() -> None:
    """Regenerate docs/PAID-SOURCES.md from the registry's `wishlist` entries.

    The paid-source list is GENERATED for the same reason TICKETS.md is: a
    price that lives only in a markdown table drifts away from the evidence
    that justified it. Every number here comes from `registry.yaml`, where it
    sits next to its dated source URL, and `loci check-sources` fails if this
    file is not a byte-identical render.
    """
    from loci import paid_sources as ps

    n, booked = ps.generate()
    rows = ps.wishlist()
    by = Counter(s["priority"] for s in rows)
    console.print(f"[green]ok[/] docs/PAID-SOURCES.md — {n} wishlist entries "
                  f"({by['P1']} P1 / {by['P2']} P2 / {by['P3']} P3), "
                  f"${booked:,}/yr booked (a lower bound: quote-only vendors "
                  f"book their price-tier floor)")


# ===========================================================================
# `loci recommendations` -- THE RECOMMENDATION LEDGER (owner ask, 2026-09-14:
# "see how long it takes for the free market to fill those gaps and if they do
# it well"). See model/recommendation_ledger.py and sql/026_recommendation.sql.
#
# Appended at the END of this file on purpose: concurrent threads hold hunks
# above, and a block that only adds lines at the bottom cannot conflict with
# any of them. `app` is already constructed and Typer registers on import, so
# placement after the __main__ guard changes nothing about invocation.
# ===========================================================================

recs_app = typer.Typer(add_completion=False, help=(
    "What we said, when, and whether the market did it. `check` is the monthly "
    "job: for every OPEN recommendation it searches the first-seen ledger and "
    "the filings pipeline for a same-category opening within the radius since "
    "the issue date. TIME-TO-FILL IS RIGHT-CENSORED until a gap fills, and a "
    "match is NOT a causal effect -- nobody read our card. The ledger buys "
    "calibration, not credit."))
app.add_typer(recs_app, name="recommendations")


def _recs_connect(read_only: bool = False):
    """Open the warehouse, waiting out a concurrent writer's lock (D69: another
    session rebuilding is the normal state here, not an error)."""
    from loci.model.recommend import connect_read_only
    from loci.model.recommendation_ledger import connect_write, ensure_schema

    if read_only:
        con = connect_read_only()
        return con
    con = connect_write()
    ensure_schema(con)
    return con


def _recs_print(rows: list[dict], title: str) -> None:
    def _s(v, dash: str = "—") -> str:
        """A pandas NULL comes back as a float NaN, and `nan or "—"` is NaN
        because NaN is TRUTHY -- which rich then refuses to render. Every cell
        goes through here."""
        return dash if v is None or v != v else str(v)

    t = Table(title=title)
    # `overflow="fold"` on the identifier columns: a rec_id truncated to
    # "r-20..." is not something you can paste into `--rec-id`, and the whole
    # point of printing it is that the reader can act on it.
    t.add_column("rec_id", justify="left", overflow="fold", no_wrap=False)
    t.add_column("issued", justify="left", no_wrap=True)
    for col, j in (("area", "left"), ("category", "left"), ("grade", "center"),
                   ("ratio", "right"), ("status", "left"), ("days", "right"),
                   ("latest match", "left"), ("fit", "right")):
        t.add_column(col, justify=j)
    for r in rows:
        colour = {"open": "yellow", "filled": "green", "withdrawn": "red",
                  "expired": "dim"}.get(r["status"], "white")
        ratio = r.get("supply_ratio_at_issue")
        days = r.get("days_open")
        score = r.get("solution_match_score")
        match = r.get("match_kind")
        match = "—" if match is None or match != match else match
        if match == "in_pipeline" and r.get("entry_stage"):
            match = f"in_pipeline ({r['entry_stage']})"
        # A withdrawn row's elapsed days measure nothing -- we retracted the
        # claim, so there is no clock still running on it.
        if r["status"] in ("withdrawn", "expired"):
            days = None
        t.add_row(_s(r["rec_id"]), _s(r["issued_on"])[:10],
                  _s(r.get("area_label") or r["area_id"]),
                  _s(r["category"]), _s(r.get("grade")),
                  "—" if ratio is None or ratio != ratio else f"{ratio:.2f}×",
                  f"[{colour}]{r['status']}[/]",
                  "—" if days is None or days != days else
                  (f"{int(days)}+" if r.get("is_censored") else f"{int(days)}"),
                  _s(match),
                  "—" if score is None or score != score else f"{score:.2f}")
    console.print(t)


@recs_app.command("backfill")
def recs_backfill(
    dry_run: bool = typer.Option(False, "--dry-run", help="Print the rows; write nothing."),
) -> None:
    """Write the ledger's first rows: the D73 laundry lead (issued 2026-09-10,
    WITHDRAWN 2026-09-11 at 0.94x) and the fifteen categories of the D74
    Gowanus card (issued 2026-09-11, grades exactly as that card printed them).

    Honest history, not fabricated leads. Idempotent on card_hash, so running
    it twice adds nothing."""
    from loci.model import recommendation_ledger as rl

    con = _recs_connect(read_only=False)
    res = rl.backfill(con, dry_run=dry_run)
    rows = rl.backfill_rows()
    _recs_print([{**r, "days_open": None, "is_censored": True, "match_kind": None,
                  "solution_match_score": None} for r in rows],
                "analysis.recommendation — backfill")
    console.print(f"[green]{'would write' if dry_run else 'written'}[/] "
                  f"{res.n_written} rows ({res.n_duplicate} already in the ledger)")
    console.print("[yellow]The 2026-09-11 card graded restaurant D; the 2026-09-13 "
                  "regeneration graded it C. The ledger records the grade AS ISSUED — "
                  "overwriting it would erase the only evidence the model moved.[/]")


@recs_app.command("add")
def recs_add(
    area: str = typer.Option(..., "--area", help="Human name for the area."),
    category: str = typer.Option(..., "--category", help="A loci category."),
    solution: str = typer.Option(..., "--solution", help="What should open, in words."),
    lon: float = typer.Option(..., "--lon", help="Anchor longitude (EPSG:4326)."),
    lat: float = typer.Option(..., "--lat", help="Anchor latitude (EPSG:4326)."),
    area_kind: str = typer.Option("bbox", "--area-kind", help="nta | address | bbox."),
    area_id: str = typer.Option(None, "--area-id", help="NTA code, address_id or bbox string."),
    address_id: str = typer.Option(None, "--address-id", help="Anchor address, if any."),
    format_hint: str = typer.Option(None, "--format-hint",
                                    help="The operating format, if the proposal names one."),
    grade: str = typer.Option(None, "--grade", help="A-D, if a card graded it."),
    ratio: float = typer.Option(None, "--supply-ratio", help="supply_ratio_vs_base at issue."),
    homes: float = typer.Option(None, "--homes-400m", help="homes_400m at issue."),
    issued_on: str = typer.Option(None, "--issued-on", help="YYYY-MM-DD; default today."),
    issued_by: str = typer.Option("hand", "--issued-by", help="Who is making this claim."),
    dry_run: bool = typer.Option(False, "--dry-run", help="Print the row; write nothing."),
) -> None:
    """Add ONE hand-entered recommendation to the ledger.

    `--format-hint` is what makes "did they do it well" answerable at all: with
    no format named, that rubric component is recorded UNAVAILABLE rather than
    scored, because "we asked for nothing specific" is not evidence that
    anybody delivered it."""
    import datetime as _dt

    from loci.model import recommendation_ledger as rl

    on = (_dt.date.fromisoformat(issued_on) if issued_on else _dt.date.today())
    row = rl._row(issued_on=on, issued_by=issued_by, area_kind=area_kind,
                  area_id=area_id or f"{lat},{lon}", area_label=area,
                  anchor_address_id=address_id, anchor_lon=lon, anchor_lat=lat,
                  category=category, proposed_solution=solution,
                  format_hint=format_hint, grade=grade,
                  supply_ratio_at_issue=ratio, homes_400m_at_issue=homes,
                  evidence={"entered_by": issued_by, "entered_at": str(_dt.date.today())})
    con = _recs_connect(read_only=False)
    res = rl.insert_rows(con, [row], dry_run=dry_run)
    if res.n_written:
        console.print(f"[green]{'would add' if dry_run else 'added'}[/] {row['rec_id']}")
    elif res.n_ineligible:
        console.print(f"[red]refused[/] {row['rec_id']}: anchor address "
                      f"{address_id!r} is legality='ineligible' (D82) — not "
                      "commercially zoned and no open business grandfathers it. "
                      "See `loci address-legality stats`.")
    else:
        console.print(f"[yellow]already in the ledger[/] (card_hash {row['card_hash']})")


@recs_app.command("list")
def recs_list(
    status: str = typer.Option(None, "--status", help="open | filled | withdrawn | expired."),
    category: str = typer.Option(None, "--category", help="Filter by loci category."),
    limit: int = typer.Option(0, "--limit", help="0 = all."),
) -> None:
    """The ledger, newest outcome attached."""
    from loci.model import recommendation_ledger as rl

    con = _recs_connect(read_only=True)
    df = rl.list_recommendations(con, status=status, category=category, limit=limit)
    if df.empty:
        console.print("[yellow]no recommendations match[/]")
        raise typer.Exit(0)
    _recs_print(df.to_dict("records"), f"analysis.recommendation_latest — {len(df)} rows")


@recs_app.command("withdraw")
def recs_withdraw(
    rec_id: str = typer.Option(..., "--rec-id", help="The recommendation to withdraw."),
    reason: str = typer.Option(..., "--reason", help="Why. REQUIRED."),
    on: str = typer.Option(None, "--on", help="YYYY-MM-DD; default today."),
    dry_run: bool = typer.Option(False, "--dry-run", help="Print; write nothing."),
) -> None:
    """Withdraw a recommendation. The row STAYS — status and reason change, and
    nothing else can. A ledger of only the leads that survived is the
    survivorship bias this table exists to defeat."""
    import datetime as _dt

    from loci.model import recommendation_ledger as rl

    con = _recs_connect(read_only=False)
    try:
        res = rl.withdraw(con, rec_id, reason,
                          on=_dt.date.fromisoformat(on) if on else None,
                          dry_run=dry_run)
    except ValueError as exc:
        console.print(f"[red]{exc}[/]")
        raise typer.Exit(1) from exc
    console.print(f"[green]{'would withdraw' if dry_run else 'withdrawn'}[/] "
                  f"{res['rec_id']}: {res['from']} -> {res['to']}")


@recs_app.command("check")
def recs_check(
    month: str = typer.Option(None, "--month", help="Snapshot month YYYY-MM; default now."),
    radius_m: float = typer.Option(None, "--radius-m",
                                   help="Match radius, STRAIGHT LINE metres (default 400)."),
    dry_run: bool = typer.Option(False, "--dry-run", help="Compute and print; write nothing."),
) -> None:
    """One month of outcome for every live recommendation. The monthly job.

    Live means open OR already filled: a filled gap still has to be observed
    every month or `still_open` is never measured after the fill. Withdrawn
    rows are not re-checked -- we retracted the claim, and scoring ourselves on
    it afterwards would be marking our own homework.

    Searches the first-seen ledger (`analysis.poi_first_seen`) and the filings
    pipeline (`analysis.storefront_pipeline`) for a SAME-CATEGORY opening
    within the radius, dated on or after the issue date and on or before the
    month's last day. DELETE + INSERT for the month, so a re-run replaces that
    month and touches no other.

    RUN IT AFTER `storefront-pipeline build` AND `poi-snapshot`: the check reads
    both, and checking against a stale ledger records an absence that the
    current data would not support.

    THE RADIUS IS A STRAIGHT LINE, not the project's usual 400 m network
    distance -- there is no persisted anchor-to-POI pair set to read. Network
    distance >= straight-line, so the disc CONTAINS the network catchment and
    the check is over-inclusive: it errs toward "the gap filled", against us.
    """
    from loci.model import recommendation_ledger as rl

    # Read-write even for --dry-run: `ensure_schema` is a CREATE TABLE IF NOT
    # EXISTS, which a read-only DuckDB connection refuses outright. Nothing is
    # written when dry_run is set; the connection is merely writable.
    con = _recs_connect(read_only=False)
    rows, res = rl.check(con, month=month, radius_m=radius_m, dry_run=dry_run)

    t = Table(title=f"analysis.recommendation_outcome — {res.month} "
                    f"(r = {res.radius_m:.0f} m straight line)")
    for col, j in (("rec_id", "left"), ("category", "left"), ("match", "left"),
                   ("date", "left"), ("days", "right"), ("dist m", "right"),
                   ("fit", "right"), ("unavailable", "left")):
        t.add_column(col, justify=j)
    import json as _json
    for r in rows:
        q = _json.loads(r["quality_json"])
        colour = {"opened": "green", "in_pipeline": "yellow", "none": "dim"}[r["match_kind"]]
        t.add_row(r["rec_id"].split("-", 2)[-1], r["rec_id"].rsplit("-", 2)[-2],
                  f"[{colour}]{r['match_kind']}[/]",
                  str(r.get("opened_on") or r.get("entry_date") or "—"),
                  "—" if r["days_to_fill"] is None else str(r["days_to_fill"]),
                  "—" if r["distance_m"] is None else f"{r['distance_m']:.0f}",
                  "—" if r["solution_match_score"] is None
                  else f"{r['solution_match_score']:.2f}",
                  ", ".join(q.get("unavailable") or []) or "—")
    console.print(t)
    console.print(f"[green]{'would write' if dry_run else 'written'}[/] "
                  f"{res.n_checked} outcome rows for {res.month}: "
                  f"{res.n_opened} opened · {res.n_in_pipeline} in pipeline · "
                  f"{res.n_none} none · {res.n_newly_filled} newly filled")
    console.print("[yellow]Time-to-fill is RIGHT-CENSORED: an open row's elapsed days "
                  "are a lower bound, and a median over the filled rows alone answers "
                  "'among gaps that filled, how fast', never 'how fast do gaps fill'. "
                  "A match is not a causal effect — nobody read our card.[/]")
    if not dry_run:
        console.print("[dim]The first-seen ledger is left-censored before 2026-10: a "
                      "location that already existed carries a NULL first-seen and "
                      "cannot read as an opening. Expect 'none' until the instrument "
                      "warms up.[/]")


@recs_app.command("report")
def recs_report(
    summary: bool = typer.Option(True, "--summary/--no-summary",
                                 help="Also print the per-category roll-up."),
) -> None:
    """The ledger with status, days open and the latest match."""
    from loci.model import recommendation_ledger as rl

    con = _recs_connect(read_only=True)
    rows = rl.report_rows(con)
    if not rows:
        console.print("[yellow]the ledger is empty — run `loci recommendations "
                      "backfill` or `loci recommend --record`[/]")
        raise typer.Exit(0)
    _recs_print(rows, f"analysis.recommendation_latest — {len(rows)} recommendations")

    if summary:
        df = rl.category_summary(con)
        t = Table(title="analysis.recommendation_category_summary")
        for col, j in (("category", "left"), ("n", "right"), ("open", "right"),
                       ("filled", "right"), ("withdrawn", "right"),
                       ("in pipeline", "right"), ("median days to fill", "right"),
                       ("still open @12m", "right")):
            t.add_column(col, justify=j)
        for _, r in df.iterrows():
            s = r["share_still_open_12m"]
            m = r["median_days_to_fill"]
            t.add_row(r["category"], str(int(r["n_recommendations"])),
                      str(int(r["n_open"])), str(int(r["n_filled"])),
                      str(int(r["n_withdrawn"])), str(int(r["n_in_pipeline"])),
                      "—" if m is None or m != m else f"{m:.0f}",
                      "no exposure" if s is None or s != s else f"{s:.0%}")
        console.print(t)
    console.print("[yellow]'days' with a + is CENSORED — the gap has not filled and the "
                  "number is a lower bound. 'fit' is solution_match_score: how much of "
                  "what we proposed open data can confirm, never a quality rating.[/]")


# ===========================================================================
# `loci ground-truth` (D105) -- WHAT IS PHYSICALLY AT THE ANCHOR. A
# human-supervised browser session opens each open recommendation on Google
# Maps / Street View, writes down every storefront it can see, and `record`
# lands the observation in analysis.address_observation. See
# model/ground_truth.py and sql/036_address_observation.sql.
#
# Placed HERE, between two sections that other sessions are appending to, so
# this hunk is contiguous and touches nothing above or below it.
# ===========================================================================

gt_app = typer.Typer(add_completion=False, help=(
    "Check what is ACTUALLY at the recommendation anchors. `plan` emits the "
    "manifest a browser session works through (one Maps URL and one Street "
    "View URL per open recommendation); `record` ingests the JSONL it writes "
    "back; `report` prints what was seen. The load-bearing output is the MISS "
    "list -- an open storefront of the recommended category standing where the "
    "supply model says there is nothing, i.e. a measured false positive of the "
    "screen. An anchor where nothing was seen is STORED, never inferred (D79)."))
app.add_typer(gt_app, name="ground-truth")


def _gt_connect(read_only: bool = False):
    """Open the warehouse, waiting out a concurrent writer's lock (D69)."""
    from loci.model.ground_truth import ensure_schema
    from loci.model.recommend import connect_read_only
    from loci.model.recommendation_ledger import connect_write

    if read_only:
        return connect_read_only()
    con = connect_write()
    ensure_schema(con)
    return con


@gt_app.command("plan")
def ground_truth_plan(
    limit: int = typer.Option(None, "--limit", help="Stop after N anchors."),
    category: str = typer.Option(None, "--category", help="One loci category only."),
    out: str = typer.Option(None, "--out", help="Manifest JSON path "
                            "(default data/ground_truth/manifest-<date>.json)."),
) -> None:
    """The manifest for a browser session: every OPEN recommendation with an
    anchor, its claim, and the two URLs to open."""
    import datetime as _dt
    import pathlib as _pl

    from loci.model import ground_truth as gt

    con = _gt_connect(read_only=True)
    entries = gt.plan(con, limit=limit, category=category)
    if not entries:
        console.print("[yellow]no open, anchored recommendations — run "
                      "`loci recommendations backfill` or `loci recommend --record`[/]")
        raise typer.Exit(0)

    t = Table(title=f"analysis.recommendation — {len(entries)} anchors to verify")
    t.add_column("rec_id", overflow="fold", no_wrap=False)
    for col, j in (("category", "left"), ("grade", "center"), ("address", "left"),
                   ("lon,lat", "left"), ("proposed", "left")):
        t.add_column(col, justify=j)
    for e in entries:
        t.add_row(e["rec_id"], e["category"], e["grade"] or "—",
                  e["address_label"] or "—",
                  f"{e['anchor_lon']:.5f},{e['anchor_lat']:.5f}",
                  (e["proposed_solution"] or "—")[:60])
    console.print(t)

    path = _pl.Path(out) if out else (
        _pl.Path("data/ground_truth") /
        f"manifest-{_dt.date.today().isoformat()}.json")
    gt.write_manifest(entries, path)
    console.print(f"[green]manifest[/] {path}")
    console.print("[yellow]Street View imagery is often months to years old. Record "
                  "its capture month in `streetview_capture_date` — an observation "
                  "is only ever as current as the panorama it was read off.[/]")


@gt_app.command("record")
def ground_truth_record(
    observations: str = typer.Argument(..., help="JSONL, one record per anchor."),
    run_id: str = typer.Option(None, "--run-id", help="Tie the rows to a run."),
    replace_run: str = typer.Option(None, "--replace-run", help=(
        "Re-ingest path: delete every analysis.address_observation row "
        "carrying this run_id, THEN ingest this file under that SAME "
        "run_id, recomputing every name match. This is how to re-ingest "
        "after a MATCHING-RULE change (e.g. the 2026-09-15 40m->400m match "
        "radius fix) -- observation_id does not change when only the rule "
        "changes, so a plain re-run leaves the OLD matched_poi_id / "
        "match_distance_m in place. Without this flag, re-running the same "
        "file is today's ordinary idempotent insert: existing rows are "
        "left untouched.")),
) -> None:
    """Ingest an observation JSONL. Idempotent: re-running the same file
    changes nothing (observation_id is sha1(rec_id|observed_at|name)) unless
    --replace-run is given."""
    from loci.model import ground_truth as gt

    con = _gt_connect(read_only=False)
    res = gt.record(con, gt.load_jsonl(observations), run_id=run_id,
                     replace_run=replace_run)
    console.print(f"[green]ok[/] {res.n_records} anchors, {res.n_rows} observation "
                  f"rows ({res.n_vacant_rows} nothing-observed), {res.n_matched} "
                  f"matched to analysis.poi_presence, {res.n_evidence} closure-evidence "
                  f"rows written; run_id {res.run_id}"
                  + (f" (replaced prior rows for run_id {replace_run})" if replace_run
                     else ""))
    console.print("[yellow]'vacant' and 'unknown' write NO evidence row: seeing "
                  "nothing is not seeing a closure (D79).[/]")


def _gt_cell(value, default: str = "—") -> str:
    """Render one table cell defensively. `gt.summary()` already turns a SQL
    NULL into a real `None` (see `ground_truth._records_nan_to_none`), but
    rich's Table.add_row still needs a `str` for every argument -- a bare
    `None` or a pandas/duckdb scalar (int64, Timestamp, ...) raises
    NotRenderableError just like the bare-NaN bug this guards against."""
    return default if value is None else str(value)


@gt_app.command("report")
def ground_truth_report() -> None:
    """What was seen at each anchor, and the supply model's misses."""
    from loci.model import ground_truth as gt

    con = _gt_connect(read_only=True)
    try:
        s = gt.summary(con)
    except RuntimeError as exc:
        # The table does not exist yet: a read-only connection cannot create
        # it, so say what would, rather than raising a Catalog Error at the
        # reader (the `recommendation_ledger.require_schema` pattern).
        console.print(f"[yellow]{exc}[/]")
        raise typer.Exit(0) from None
    if not s["by_rec"]:
        console.print("[yellow]nothing observed yet — run `loci ground-truth plan` "
                      "then `loci ground-truth record <file.jsonl>`[/]")
        raise typer.Exit(0)

    t = Table(title=f"analysis.address_observation — {len(s['by_rec'])} anchors checked")
    t.add_column("rec_id", overflow="fold", no_wrap=False)
    for col, j in (("category", "left"), ("verdict", "left"), ("storefronts", "right"),
                   ("open", "right"), ("closed", "right"), ("vacant", "right"),
                   ("matched", "right"), ("same-cat open", "right"), ("imagery", "left")):
        t.add_column(col, justify=j)
    for r in s["by_rec"]:
        t.add_row(_gt_cell(r["rec_id"]), _gt_cell(r["category"]), _gt_cell(r["gap_verdict"]),
                  str(int(r["n_storefronts"])), str(int(r["n_open"])),
                  str(int(r["n_closed"])), str(int(r["n_vacant"])),
                  str(int(r["n_matched"])), str(int(r["n_same_category_open"])),
                  _gt_cell(r["imagery"]))
    console.print(t)

    if s["misses"]:
        m = Table(title="analysis.address_observation_miss — the supply model's misses")
        m.add_column("rec_id", overflow="fold", no_wrap=False)
        for col in ("category", "observed storefront", "guess", "status"):
            m.add_column(col)
        for r in s["misses"]:
            m.add_row(_gt_cell(r["rec_id"]), _gt_cell(r["category"]),
                      _gt_cell(r["storefront_name"]), _gt_cell(r["category_guess"]),
                      _gt_cell(r["status"]))
        console.print(m)
        console.print("[red]Each row above is an open business of the recommended "
                      "category standing at an anchor the screen called empty — a "
                      "MEASURED false positive, not an estimate.[/]")
    else:
        console.print("[green]no misses[/] — every open storefront of a recommended "
                      "category at a checked anchor is already in analysis.poi_presence")


# ===========================================================================
# retrodiction (GTM-158, QUESTIONS T11) -- gates every decision-value claim
# in docs/GTM.md (D87). Appended at the END of this file; nothing above is
# touched, because two sessions are appending here concurrently.
# ===========================================================================
retrodiction_app = typer.Typer(add_completion=False, help=(
    "Score storefronts that opened at a known date with the screen AS IT WOULD "
    "HAVE READ ON THAT DATE, then check what happened. Two halves: a SURVIVAL "
    "test that is gated shut because Loci has one snapshot and every closure "
    "instrument in the warehouse is a current-state extract, and an ENTRY test "
    "that is identifiable today -- did the 2023-24 openings land where the "
    "frozen score said the gaps were, or where supply was already thick?"))
app.add_typer(retrodiction_app, name="retrodiction")


@retrodiction_app.command("run")
def retrodiction_run(
    window: str = typer.Option("2023-01:2024-12", "--window",
                               help="Opening window, YYYY-MM:YYYY-MM."),
    radius_m: float = typer.Option(400.0, "--radius-m",
                                   help="Straight-line catchment radius, EPSG:32618."),
    sample_n: int = typer.Option(12000, "--sample-n",
                                 help="Addresses in the entry panel (deterministic)."),
    permutations: int = typer.Option(200, "--permutations",
                                     help="Draws in the within-category placebo null."),
    strict_dated: bool = typer.Option(True, "--strict-dated/--no-strict-dated",
                                      help="Also run with D79's undated rows dropped."),
    out: str = typer.Option(None, "--out", help="Output directory "
                            "(default data/retrodiction)."),
) -> None:
    """Build the cohort, audit the closure instruments, gate the survival model,
    fit the entry model.

    Read-only on the warehouse and safe to run beside a session rebuilding
    `analysis.address_category`; the lock is retried, never forced.
    """
    from loci.validation import retrodiction as rd

    rep = rd.run(window=window, radius_m=radius_m, sample_n=sample_n,
                 permutations=permutations, out=out, strict_dated=strict_dated)
    e = rep["entry"]
    nos = e.get("auc_no_score", e["permutation_null"]["mean"])
    console.print(f"[green]ok[/] cohort {rep['cohort_n']:,}; "
                  f"POI-cohort closures "
                  f"{rep['survival']['n_events_observable']} of "
                  f"{rep['survival']['min_events_required']} required; "
                  f"entry AUC {e['auc_full']:.4f} vs {nos:.4f} for the SAME "
                  f"model without the score (lift "
                  f"{e['auc_full'] - nos:+.4f}) — the homes-only figure "
                  f"{e['auc_homes_only']:.3f} is not the fair comparator")
    console.print("[yellow]`loci retrodiction report` renders the full result.[/]")


@retrodiction_app.command("report")
def retrodiction_report(
    out: str = typer.Option(None, "--out", help="Directory holding summary.json."),
) -> None:
    """Render the last run: cohort, closure audit, survival verdict, entry test."""
    from loci.validation import retrodiction as rd

    rep = rd.load(out)
    p = rep["params"]
    console.print(Panel.fit(
        f"window {p['window']}  radius {p['radius_m']:.0f} m ({p['distance']})\n"
        f"snapshot {p['snapshot']}  sample {p['sample_n']:,} addresses  "
        f"seed {p['seed']}\nran {p['ran_at']}",
        title="retrodiction"))

    sel = rep["selection"]
    console.print(f"\n[bold]Cohort[/] — {sel['n_cohort']:,} dated openings in MN+BK, "
                  f"{sel['n_cohort_principled']:,} of them in the principled supply "
                  f"set; {sel['food_share']:.0%} are restaurant / cafe / bar.")
    t = Table(show_header=True, header_style="bold")
    for c in ("category", "in cohort", "dated share of category", "censored"):
        t.add_column(c)
    for r in sorted(sel["by_category"], key=lambda r: -r["in_cohort"]):
        t.add_row(str(r["category"]), f"{int(r['in_cohort']):,}",
                  f"{r['dated_share']:.0%}", f"{int(r['backfill_censored']):,}")
    console.print(t)

    console.print("\n[bold]Closure instruments[/] — can a closure be OBSERVED at all?")
    t = Table(show_header=True, header_style="bold")
    for c in ("instrument", "usable", "closures", "why"):
        t.add_column(c, overflow="fold")
    for i in rep["closure"]:
        t.add_row(i["name"], "yes" if i["available"] else "[red]no[/]",
                  f"{i['observable_closures']:,}", i["reason"])
    console.print(t)

    s = rep["survival"]
    style = "green" if s["identified"] else "red"
    console.print(Panel.fit(
        f"{s['verdict']}\n\n{s['n_events_observable']} observable closures against a "
        f"floor of {s['min_events_required']}.\n{s['power_basis']}\n\n"
        f"Censoring: {s['censoring']}\n\nWhat unlocks it: "
        f"{s['what_a_second_snapshot_adds']}",
        title="survival", border_style=style))

    for label, e in (("entry (censored rows counted as present at t0)", rep["entry"]),
                     ("entry (--strict-dated: undated rows dropped)",
                      rep.get("entry_strict") or {})):
        if not e:
            continue
        console.print(f"\n[bold]{label}[/] — {e['n_rows']:,} address x category rows, "
                      f"{e['n_ntas']} NTAs, opening rate {e['opening_rate']:.1%}")
        t = Table(show_header=True, header_style="bold")
        for c in ("measure", "value"):
            t.add_column(c, overflow="fold")
        t.add_row("blocked-CV AUC (full)",
                  f"{e['auc_full']:.3f}  [{e['auc_full_ci'][0]:.3f}, "
                  f"{e['auc_full_ci'][1]:.3f}]")
        nos = e.get("auc_no_score", e["permutation_null"]["mean"])
        t.add_row("[bold]blocked-CV AUC (same model, NO score)[/]",
                  f"[bold]{nos:.4f}[/]  <- the fair comparator")
        t.add_row("[bold]HEADLINE lift over the no-score model[/]",
                  f"[bold]{e['auc_full'] - nos:+.4f}[/]")
        t.add_row("blocked-CV AUC (homes only)",
                  f"{e['auc_homes_only']:.3f}  [{e['auc_homes_only_ci'][0]:.3f}, "
                  f"{e['auc_homes_only_ci'][1]:.3f}]  (flatters — density + "
                  f"retail_index + category FE alone reach the no-score figure)")
        t.add_row("lift over homes-only (NOT the headline)",
                  f"{e['auc_lift']:+.3f}  beats baseline: {e['beats_baseline']}")
        t.add_row("permutation null (p95 / max)",
                  f"{e['permutation_null']['p95']:.3f} / "
                  f"{e['permutation_null']['max']:.3f}  "
                  f"beats placebo: {e['beats_placebo']}")
        t.add_row("D1 SIGN on t0 supply ratio",
                  f"[bold]{e['d1_sign']}[/]  95% CI "
                  f"[{e['d1_score_ci'][0]:+.2f}, {e['d1_score_ci'][1]:+.2f}]")
        t.add_row("own-category-gap flag (zero competitors at t0)",
                  f"95% CI [{e['d1_own_gap_ci'][0]:+.2f}, "
                  f"{e['d1_own_gap_ci'][1]:+.2f}]")
        h = e.get("hard_outcome")
        if h:
            t.add_row(f"AUC on '{h['outcome']}' ({h['rate']:.0%} positive)",
                      f"{h['auc_full']:.3f} vs homes-only {h['auc_homes_only']:.3f}")
        console.print(t)

        t = Table(show_header=True, header_style="bold")
        for c in ("category", "n", "opening rate", "t0 supply-ratio coef (95% CI)",
                  "own-gap coef (95% CI)", "AUC", "AUC homes"):
            t.add_column(c, overflow="fold")
        for cat, r in sorted(e["by_category"].items()):
            if "skipped" in r:
                t.add_row(cat, f"{r['n']:,}", "—", r["skipped"], "—", "—", "—")
                continue
            t.add_row(cat, f"{r['n']:,}", f"{r['opening_rate']:.1%}",
                      f"{r['log_score_coef']:+.2f} "
                      f"[{r['log_score_ci'][0]:+.2f}, {r['log_score_ci'][1]:+.2f}]",
                      f"{r['own_gap_coef']:+.2f} "
                      f"[{r['own_gap_ci'][0]:+.2f}, {r['own_gap_ci'][1]:+.2f}]",
                      f"{r['auc']:.3f}", f"{r['auc_homes_only']:.3f}")
        console.print(t)

    console.print("\n[yellow]Entry is not survival. This says where capital WENT, "
                  "never whether it was right to go there. A positive sign on the t0 "
                  "supply ratio means openings followed existing supply — which is "
                  "D87's attack surviving, not the screen being validated.[/]")


@retrodiction_app.command("events")
def retrodiction_events(
    window: str = typer.Option("2023-01:2024-12", "--window",
                               help="Opening window, YYYY-MM:YYYY-MM."),
) -> None:
    """Recount cohort closure EVENTS live, via the shared open/closed/unknown
    predicate (`model.poi_presence.poi_is_open`) -- without re-running the
    full entry model.

    `report` only renders the LAST `run`'s saved summary.json, which freezes
    whatever `closure_audit` computed at run time. This answers "what would
    that count be right now" against the live warehouse, read-only.
    """
    import datetime as _dt

    from loci.validation import retrodiction as rd

    a, b = window.split(":")
    start = _dt.date(int(a[:4]), int(a[5:7]), 1)
    y, m = int(b[:4]), int(b[5:7])
    end = (_dt.date(y + (m == 12), 1 if m == 12 else m + 1, 1) - _dt.timedelta(days=1))

    con = rd.connect(read_only=True)
    try:
        counts = rd.cohort_closure_events(con, start, end)
    finally:
        con.close()
    console.print(Panel.fit(
        f"window {start}:{end}\n"
        f"cohort openings in window: {counts['n_cohort']:,}\n"
        f"[bold]cohort events (poi_is_open = 'closed'): "
        f"{counts['n_cohort_events']:,}[/]\n"
        f"floor for a hazard model: {rd.MIN_EVENTS_FOR_HAZARD}\n"
        f"warehouse-wide rows reading 'closed' under the predicate: "
        f"{counts['n_predicate_closed_total']:,}",
        title="retrodiction events (live, via poi_is_open)"))


# ---------------------------------------------------------------------------
# poi-closures -- make CLOSURES observable (docs/retrodiction-2026-09.md §4)
# ---------------------------------------------------------------------------
poi_closures_app = typer.Typer(help="Source-published storefront CLOSURES.")
app.add_typer(poi_closures_app, name="poi-closures")


@poi_closures_app.command("ingest")
def poi_closures_ingest(
    release: str = typer.Option(None, "--release",
                                help="Foursquare OS Places release, e.g. 2026-08-11. "
                                     "Default: the adapter's LOCI_FSQ_RELEASE."),
    refetch: bool = typer.Option(False, "--refetch",
                                 help="Re-download the unfiltered NYC extract even if "
                                      "it is already cached."),
    dry_run: bool = typer.Option(False, "--dry-run",
                                 help="Count and print; write nothing."),
) -> None:
    """Re-pull Foursquare OS Places WITHOUT the open-only filter and load the
    closed venues into `staging.poi_closure`.

    The 2026-09 retrodiction found ZERO observable closures in the warehouse —
    not because New York closes no storefronts, but because
    `sources/universal/foursquare_places._ensure_cache` fetched with
    `WHERE date_closed IS NULL`. The column was in the schema all along. This
    pulls the same release and bbox into its OWN file
    (`data/raw/foursquare_closed/`) and loads only the closed rows.

    THE SUPPLY SET IS NOT TOUCHED. Nothing here writes `staging.poi`,
    `analysis.poi_dedup` or `analysis.poi_supply`; the open cache and the
    adapter's `normalize()` are unchanged, so no closed venue can enter the
    screen's supply. Then run `loci poi-snapshot` to fill the ledger's
    `closed_on` / `closed_src`.

        loci poi-closures ingest
    """
    from loci.model import poi_closure as pc
    from loci.model import poi_presence as pp
    from loci.sources.universal import foursquare_places as fsq

    rel = release or fsq.RELEASE
    console.print(f"[dim]Foursquare OS Places release {rel} — NYC bbox, "
                  "no open-only filter…[/]")
    try:
        path = fsq.ensure_closed_cache(rel, force=refetch)
    except RuntimeError as exc:
        console.print(f"[red]FAIL[/] {exc}")
        raise typer.Exit(1) from exc
    console.print(f"[green]raw[/] {path}")

    con = pp.connect_write()
    try:
        report = pc.load(con, release=rel, dry_run=dry_run)
    except RuntimeError as exc:
        console.print(f"[red]FAIL[/] {exc}")
        raise typer.Exit(1) from exc

    t = Table(title=f"poi-closures ingest {rel}"
                    + (" — DRY RUN, nothing written" if dry_run else ""))
    t.add_column("metric"); t.add_column("n", justify="right")
    t.add_row("closed venues loaded", f"{report['rows']:,}")
    t.add_row("  mapped to a Loci category", f"{report['mapped']:,}")
    t.add_row("  carrying a ledger key", f"{report['keyed']:,}")
    console.print(t)

    y = Table(title="date_closed by year")
    y.add_column("year"); y.add_column("n", justify="right")
    for yr, n in sorted(report["by_year"].items()):
        y.add_row(str(yr), f"{n:,}")
    console.print(y)

    if dry_run:
        console.print("[yellow]--dry-run: staging.poi_closure not written.[/]")
        raise typer.Exit(0)
    console.print("[yellow]NOTE[/] a NULL closed_on is “no closure observed”, never "
                  "“still open”. Foursquare marks a venue closed when its pipeline "
                  "learns of it — late for a check-in base, and often never for the "
                  "categories nobody checks in at. Survival built on this is an "
                  "UPPER BOUND, and the bias is categorical, so it does not cancel.")
    console.print("[dim]next: `loci poi-snapshot` fills analysis.poi_presence."
                  "closed_on / closed_src from this table.[/]")


@poi_closures_app.command("stats")
def poi_closures_stats() -> None:
    """Counts for `staging.poi_closure` and its join to the first-seen ledger.

    Read-only. The number that matters is how many LEDGER rows now carry a
    closure date — that is the event count a survival model would be fitted on.
    """
    from loci.model import poi_closure as pc
    from loci.model.recommend import connect_read_only

    con = connect_read_only()
    try:
        s = pc.stats(con)
    except Exception as exc:            # noqa: BLE001 -- duckdb raises several
        console.print(f"[red]FAIL[/] {exc} — run `loci poi-closures ingest` first")
        raise typer.Exit(1) from exc

    t = Table(title="staging.poi_closure")
    t.add_column("metric"); t.add_column("n", justify="right")
    t.add_row("closed venues", f"{s['closures']:,}")
    t.add_row("  mapped to a Loci category", f"{s['mapped']:,}")
    t.add_row("  no ledger row at this key", f"{s['unmatched']:,}")
    t.add_row("ledger rows", f"{s['ledger_rows']:,}")
    t.add_row("  with an observed closure", f"{s['ledger_closed']:,}")
    console.print(t)

    c = Table(title="ledger closures by category")
    for col in ("category", "closed", "rows", "rate"):
        c.add_column(col, justify="right" if col != "category" else "left")
    for cat, closed, rows in s["ledger_closed_by_category"]:
        c.add_row(str(cat), f"{closed:,}", f"{rows:,}",
                  f"{(closed / rows if rows else 0):.1%}")
    console.print(c)

    k = Table(title="ledger closures by first_seen_kind")
    for col in ("first_seen_kind", "closed", "rows"):
        k.add_column(col, justify="right" if col != "first_seen_kind" else "left")
    for kind, closed, rows in s["ledger_closed_by_kind"]:
        k.add_row(str(kind), f"{closed:,}", f"{rows:,}")
    console.print(k)

    console.print("[yellow]A closure here is a SOURCE-PUBLISHED date_closed and "
                  "nothing else. Absence from a snapshot is not a closure (D79); "
                  "`last_seen_month` falling behind is a prompt to look.[/]")


# ===========================================================================
# retrodiction go-dark (GTM-158) -- the LL157 premises outcome the first pass
# wrongly rejected. Appended at the END of this file, after the poi-closures
# block; nothing above is touched.
# ===========================================================================
@retrodiction_app.command("go-dark")
def retrodiction_go_dark(
    base_year: int = typer.Option(2022, "--base-year",
                                  help="Premises must be OCCUPIED at this year's 12-31."),
    outcome_year: int = typer.Option(2024, "--outcome-year",
                                     help="Vacancy is read at this year's 12-31."),
    radius_m: float = typer.Option(400.0, "--radius-m",
                                   help="Straight-line catchment, EPSG:32618."),
    out: str = typer.Option(None, "--out", help="Output directory."),
) -> None:
    """Does a THIN-supply score at 2023-01-01 predict a storefront going dark?

    Business-level survival for the POI cohort is not identified (one snapshot,
    current-state sources). Premises-level go-dark IS: `analysis.storefront` is
    a premises x year panel and, in MN+BK, 1,080 premises occupied at 2022-12-31
    were vacant at 2024-12-31. That is 22x the pre-declared 48-event floor,
    inside the window, with no new data.

    Reported in BOTH attrition variants, because the 3,510 premises that stop
    filing are plausibly the distressed ones and nothing inside LL157 can say.
    Split on `construction_reported`, because a gut renovation is not a failure.
    """
    from loci.validation import retrodiction as rd

    rep = rd.run_go_dark(base_year=base_year, outcome_year=outcome_year,
                         radius_m=radius_m, out=out)
    s = rep["strict"]
    console.print(f"[green]ok[/] strict n {s['n']:,} / {s['events']:,} events "
                  f"({s['event_rate']:.1%}); AUC {s['auc_full']:.3f} vs "
                  f"{s['auc_no_score']:.3f} without the score")
    console.print("[yellow]`loci retrodiction go-dark-report` renders it.[/]")


@retrodiction_app.command("go-dark-report")
def retrodiction_go_dark_report(
    out: str = typer.Option(None, "--out", help="Directory holding go_dark.json."),
) -> None:
    """Render the go-dark run: both attrition variants, splits, calibration."""
    from loci.validation import retrodiction as rd

    rep = rd.load_go_dark(out)
    p = rep["params"]
    console.print(Panel.fit(
        f"occupied {p['base_year']}-12-31 -> vacant {p['outcome_year']}-12-31\n"
        f"score frozen 2023-01-01, {p['radius_m']:.0f} m {p['distance']}\n"
        f"ran {p['ran_at']}",
        title="LL157 go-dark"))

    for label in ("strict", "attrition_as_event"):
        v = rep[label]
        console.print(f"\n[bold]{label}[/] — n {v['n']:,}, {v['events']:,} events "
                      f"({v['event_rate']:.1%}), {v['n_ntas']} NTAs, "
                      f"{v['n_blocks']} spatial blocks, NTA fixed effects "
                      f"{v['nta_fixed_effects']}")
        t = Table(show_header=True, header_style="bold")
        for c in ("measure", "value"):
            t.add_column(c, overflow="fold")
        t.add_row("block-held-out AUC (with score)", f"{v['auc_full']:.4f}")
        t.add_row("block-held-out AUC (no score)", f"{v['auc_no_score']:.4f}")
        t.add_row("lift", f"{v['auc_lift']:+.4f}")
        t.add_row("t0 supply score coef",
                  f"{v['log_score_coef']:+.3f}  95% CI "
                  f"[{v['log_score_ci'][0]:+.3f}, {v['log_score_ci'][1]:+.3f}]  "
                  f"p {v['log_score_p']:.3g}")
        t.add_row("SIGN", f"[bold]{v['sign']}[/]")
        console.print(t)

        t = Table(title="by LL157 activity group (Bonferroni alpha = 0.0167)",
                  show_header=True, header_style="bold")
        for c in ("group", "n", "events", "rate", "coef (95% CI)", "p", "survives"):
            t.add_column(c, overflow="fold")
        for g, r in sorted(v["by_activity_group"].items()):
            if "skipped" in r:
                t.add_row(g, f"{r['n']:,}", "—", "—", r["skipped"], "—", "—")
                continue
            t.add_row(g, f"{r['n']:,}", f"{r['events']:,}", f"{r['rate']:.1%}",
                      f"{r['log_score_coef']:+.3f} [{r['log_score_ci'][0]:+.3f}, "
                      f"{r['log_score_ci'][1]:+.3f}]", f"{r['p']:.3g}",
                      "yes" if r["survives_bonferroni"] else "no")
        console.print(t)

        t = Table(title="split on construction_reported", show_header=True,
                  header_style="bold")
        for c in ("split", "n", "events", "rate", "coef (95% CI)"):
            t.add_column(c, overflow="fold")
        for g, r in v["by_construction"].items():
            if "skipped" in r:
                t.add_row(g, f"{r['n']:,}", "—", "—", r["skipped"])
                continue
            t.add_row(g, f"{r['n']:,}", f"{r['events']:,}", f"{r['rate']:.1%}",
                      f"{r['log_score_coef']:+.3f} [{r['log_score_ci'][0]:+.3f}, "
                      f"{r['log_score_ci'][1]:+.3f}]")
        console.print(t)

        t = Table(title="calibration (in-sample deciles)", show_header=True,
                  header_style="bold")
        for c in ("decile", "n", "predicted", "observed"):
            t.add_column(c, justify="right")
        for c in v["calibration"]:
            t.add_row(str(c["decile"]), f"{c['n']:,}", f"{c['predicted']:.3f}",
                      f"{c['observed']:.3f}")
        console.print(t)

    console.print("\n[yellow]LL157 is LANDLORD SELF-REPORT. Vacancy is not failure "
                  "(hence the construction split), a premises is a building not a "
                  "shop (any reported unit going dark counts), and the filing "
                  "universe is selected. This is the identifiable survival-adjacent "
                  "outcome Loci has today — not a business-level survival rate.[/]")


@app.command(name="forecast-export")
def forecast_export_cmd(
    boroughs: str = typer.Option("MN,BK", help="Comma-separated borough codes (MN|BX|BK|QN|SI)."),
    out_dir: Path = typer.Option(REPO_ROOT / "webmap" / "data", help="Output directory."),
    dry_run: bool = typer.Option(False, "--dry-run",
                                 help="Print the three blocks' counts; write nothing."),
) -> None:
    """Write webmap/data/forecast.json — the MODELED / REALIZED / SURPRISE mode.

    ONE FILE, ON ITS OWN COMMAND. `loci export-webmap` writes this file too, but
    a new forecast vintage must not cost the 90-second full export: this command
    re-derives the gap files' address order with `gap_id_order` and rewrites the
    single file the mode fetches. The order rule is stated in one place, so the
    two commands cannot attach a probability to a different doorway.

    The three blocks are independently available and each says so: `modeled`
    needs analysis.forecast (sql/028), `realized` needs only the presence and
    closure ledgers, and `surprise` needs a scored outcome. "Not scored yet" is
    printed as not-measured, never as zero.
    """
    from loci.viz import webmap_export as wx

    boros = [b.strip().upper() for b in boroughs.split(",") if b.strip()]
    con = _dot_connect(read_only=True)
    fc = wx.collect_forecast(con, boros)
    rep = wx.forecast_summary(fc)

    console.print(f"vintage [bold]{rep['issuedMonth'] or 'none issued'}[/]"
                  f" · model [bold]{rep['modelVersion'] or '—'}[/]"
                  f" · newest scored month [bold]{rep['scoredMonth'] or 'none scored'}[/]")
    for block, label in (("modeled", "MODELED"), ("realized", "REALIZED"),
                         ("surprise", "SURPRISE")):
        if not rep[f"{block}Available"]:
            console.print(f"[yellow]{label}: not measured[/] — {rep[f'{block}Reason']}")
    win = rep["realizedWindow"]
    table = Table(title="forecast.json" + ("  [DRY RUN — nothing written]" if dry_run else ""))
    table.add_column("category")
    table.add_column("modeled addresses", justify="right")
    table.add_column(f"openings {win[0] or '?'}→{win[1] or '?'}", justify="right")
    table.add_column("closures", justify="right")
    table.add_column("pipeline", justify="right")
    table.add_column("surprise NTAs", justify="right")
    for cat in wx.ALLCATS:
        r = rep["realized"].get(cat) or {}
        table.add_row(cat, f"{rep['modeled'].get(cat, 0):,}",
                      f"{r.get('open', 0):,}", f"{r.get('closed', 0):,}",
                      f"{r.get('pipe', 0):,}", f"{rep['surprise'].get(cat, 0):,}")
    console.print(table)

    if dry_run:
        console.print("[yellow]dry run[/] — nothing written")
        return
    written = wx.write_forecast(fc, Path(out_dir))
    for rel, size in written.items():
        console.print(f"[green]ok[/] {Path(out_dir) / rel} — {size:,} bytes")
    # The sidebar section is gated on meta.json's `forecast` block, so a new
    # vintage that did not reach it would be invisible. Written by the same
    # `forecast_meta` the full export uses, so the two cannot disagree.
    if wx.patch_meta_forecast(fc, Path(out_dir)):
        console.print(f"[green]ok[/] {Path(out_dir) / 'meta.json'} — forecast legend refreshed")
    else:
        console.print("[yellow]no meta.json[/] — run `loci export-webmap` before the map "
                      "can show this layer")
    console.print("[yellow]p_opening forecasts ENTRY, not viability (D88). Closures are "
                  "~3% ascertained; absence is not a closure.[/]")


# ===========================================================================
# `loci gen-portability` -- THE PORTABILITY AUDIT (owner ask, 2026-09-14:
# "what are the critical inputs necessary to be able to expand the model to
# new cities"). See portability.py and the `portability:` blocks in
# registry.yaml.
#
# Appended at the END of this file, for the same reason the recommendations
# block above is: concurrent threads hold hunks higher up, and a block that
# only adds lines at the bottom cannot conflict with any of them.
# ===========================================================================


@app.command(name="gen-portability")
def gen_portability() -> None:
    """Regenerate docs/PORTABILITY.md from the registry's `portability` blocks.

    GENERATED, exactly like PAID-SOURCES.md and TICKETS.md: `loci
    check-sources` fails if the file is not a byte-identical render. The
    reason it matters more here than anywhere else is that a readiness matrix
    which CAN be hand-edited is one that will be hand-edited into optimism.

    Three things come out of it: the registry grouped by portability class and
    by pipeline stage; the MINIMUM INPUT SET per evidence grade, computed the
    way `recommend.py` computes a verdict (the minimum over the load-bearing
    sections of `recommend_grades.yaml`); and the dated second-city portal
    survey. Nothing is ingested for any city but New York.
    """
    from loci import portability as pt

    n, n_unique = pt.generate()
    cls = pt.by_class()
    console.print(f"[green]ok[/] docs/PORTABILITY.md — {n} sources classed "
                  + ", ".join(f"{len(cls[c])} {c}" for c in pt.CLASS_ORDER)
                  + f" ({n_unique} with no equivalent anywhere else)")

    t = Table(title="minimum input set by evidence grade", show_header=True,
              header_style="bold")
    for c in ("grade", "verdict", "registry sources", "of those, per-city/state",
              "not a registry source"):
        t.add_column(c, overflow="fold")
    byid = pt.sources_by_id()
    for grade in ("B", "C", "D"):
        req = pt.minimum_input_set(grade)
        per_city = sum(1 for sid in req["sources"]
                       if byid[sid]["portability"]["class"]
                       in {"state", "city_open_data", "city_unique"})
        note = f"{len(req['also'])}"
        if req["paid_sections"]:
            note += " [red](PAID: " + ", ".join(req["paid_sections"]) + ")[/]"
        if req["blocked_by"]:
            note += " [red](UNREACHABLE: " + ", ".join(req["blocked_by"]) + ")[/]"
        t.add_row(grade, req["verdict"], str(len(req["sources"])), str(per_city), note)
    console.print(t)

    if pt.CITY_PROBE:
        t = Table(title=f"second-city readiness ({pt.PROBE_DATE}, research only)",
                  show_header=True, header_style="bold")
        t.add_column("input", overflow="fold")
        for c in pt.CITY_PROBE:
            t.add_column(c["city"])
        for inp in pt.PROBE_INPUTS:
            t.add_row(inp, *[pt.STATUS_MARK[c["inputs"][inp]["status"]]
                             for c in pt.CITY_PROBE])
        t.add_row("[bold]grade on day one[/]",
                  *[f"[bold]{c['grade_today']}[/]" for c in pt.CITY_PROBE])
        t.add_row("[bold]ceiling after a local refit[/]",
                  *[f"[bold]{c['grade_ceiling']}[/]" for c in pt.CITY_PROBE])
        console.print(t)

    console.print("[yellow]The portal survey is RESEARCH ONLY — no adapter exists for "
                  "any city but New York, and every distance in Loci is a WALK distance "
                  "calibrated on Manhattan and Brooklyn (D48). A city that reads green "
                  "on every row still needs the DNCI constants, the density "
                  "elasticities and the revenue calibration refitted.[/]")


# ===========================================================================
# forecast ledger -- the MODELLED layer, issued as dated, scoreable predictions.
# Appended at the END of this file; nothing above is touched.
# ===========================================================================
forecast_app = typer.Typer(add_completion=False, help=(
    "THE MODELLED LAYER. `analysis.address_category` is what the data reads at "
    "a doorway today; this is what a model FROZEN ON A DATE says will happen "
    "next, together with the record of whether it was right. A prediction that "
    "is not dated and scored is not a prediction. Forecasts ENTRY -- whether "
    "the market puts a same-category storefront within 400 m in twelve months "
    "-- and never VIABILITY (D88). Schema and reasoning: sql/028_forecast.sql."))
app.add_typer(forecast_app, name="forecast")


@forecast_app.command("issue")
def forecast_issue(
    month: str = typer.Option(..., "--month", help="Issue month, YYYY-MM. "
                              "Features freeze at its FIRST day."),
    model_version: str = typer.Option(None, "--model-version",
                                      help="Override the computed version. Use "
                                           "only to reproduce an old vintage."),
    horizon: int = typer.Option(12, "--horizon-months"),
    radius_m: float = typer.Option(400.0, "--radius-m",
                                   help="Straight-line catchment, EPSG:32618."),
    sample_n: int = typer.Option(12000, "--sample-n",
                                 help="Addresses in the fit and anchor sample "
                                      "(deterministic, hash-ordered)."),
    limit_points: int = typer.Option(None, "--limit-points",
                                     help="Cap the PREDICTION frame. For smoke "
                                          "tests only -- a real vintage covers "
                                          "every lot address."),
    dry_run: bool = typer.Option(False, "--dry-run",
                                 help="Fit and predict, write nothing."),
    force: bool = typer.Option(False, "--force",
                               help="Re-issue an (issued_month, model_version) "
                                    "that already has a forecast_run row. "
                                    "Without it, issue REFUSES rather than "
                                    "overwrite silently."),
) -> None:
    """Fit on data available at --month, then predict every lot address x category.

    THE LEAKAGE CONTRACT. The model is fitted on two stacked folds with t0 at
    --month minus 24 and minus 12 months, each carrying features frozen at its
    own t0 and an outcome observed over its own following 12 months. Nothing
    dated on or after --month enters the fit, the features or the anchor
    median. `tests/test_forecast.py` pins that against a ledger row dated after
    the issue month.

    THE VINTAGE DISCIPLINE. Idempotent per (issued_month, model_version) by
    DELETE+INSERT: re-running the same model on the same month reproduces that
    month's answer. A NEW model gets a NEW version and its own vintages, and a
    past vintage is NEVER re-issued with a newer model -- that would be a
    measurement of hindsight, not a track record.

    THE SUPPLY-SET IDENTITY (D96, GTM-163 addendum). `model_version` hashes
    `score.supply.supply_hash(con)` and the closure-gate flag alongside the
    feature list -- so two fits on the SAME form but a DIFFERENT canonical POI
    set (a peer's baseline re-fit, an anchor re-measurement) get DIFFERENT
    versions by construction, and `analysis.forecast_run.supply_hash` records
    which one a stored vintage rests on. Because of that, this command REFUSES
    to reuse an (issued_month, model_version) that already exists unless
    --force is passed -- printing the supply hash it is about to fit on first,
    so a hurried re-run is not the way a reader finds out the supply moved
    under an unchanged month.

    Reads first, writes last: the fit and the four-million-row prediction run
    on a read-only handle, so a peer session holding the warehouse lock costs
    only the final write, which waits up to 45 minutes for it.
    """
    from loci.model import forecast as fc

    say = lambda m: console.print(f"[dim]{m}[/]")       # noqa: E731
    kw = dict(version=model_version, horizon=horizon, radius_m=radius_m,
              sample_n=sample_n, limit_points=limit_points)

    # THE REFUSE-WITHOUT-FORCE CHECK, before the expensive fit: resolve what
    # version THESE settings and THIS supply set would produce and print the
    # supply hash regardless, so a reader always sees it -- not only on a
    # refusal.
    probe = fc.connect_read()
    try:
        probe_ver, probe_hash = fc.resolve_version(
            probe, version=model_version, horizon=horizon, radius_m=radius_m)
        console.print(f"[dim]supply hash this vintage will fit on: "
                      f"{probe_hash}[/]")
        fc.guard_reissue(probe, month, probe_ver, force=force)
    except fc.AlreadyIssuedError as exc:
        console.print(f"[red]refusing:[/] {exc}")
        raise typer.Exit(code=1) from exc
    finally:
        probe.close()

    if dry_run:
        con = fc.connect_read()
        try:
            rep = fc.issue(con, month, dry_run=True, progress=say, **kw)
        finally:
            con.close()
        rep.pop("_pred", None)
        rep.pop("_t0", None)
    else:
        # ONE HANDLE AT A TIME. DuckDB refuses a second connection to the same
        # file with a different configuration inside one process, and read_only
        # is exactly such a difference -- so the fit and the prediction run on a
        # read handle, which is CLOSED before the write handle is asked for.
        rep = fc.issue_managed(month, progress=say, **kw)
    f = rep["fit"]

    console.print(Panel.fit(
        f"vintage [bold]{rep['issued_month']}[/]  model [bold]{rep['model_version']}[/]\n"
        f"horizon {rep['horizon_months']} months · {rep['radius_m']:.0f} m straight-line\n"
        f"fit folds {', '.join(str(d) for d in fc.fit_t0s(month, horizon))}\n"
        f"rows issued {rep['n_rows_issued']:,}"
        + ("  [yellow](dry run — nothing written)[/]" if dry_run else ""),
        title="forecast issued"))

    t = Table(title="the fit, out of sample with WHOLE NTAs held out")
    t.add_column("measure"); t.add_column("value", justify="right")
    t.add_row("fit rows / addresses / NTAs",
              f"{f['n_rows']:,} / {f['n_addresses']:,} / {f['n_ntas']}")
    t.add_row("positive rate", f"{f['positive_rate']:.1%}")
    t.add_row("blocked-CV AUC", f"{f['auc_blocked']:.4f}")
    t.add_row("  vs NO-SCORE baseline  [THE BAR]", f"{f['auc_no_score']:.4f}")
    t.add_row("  vs PERSISTENCE baseline", f"{f['auc_persistence']:.4f}")
    t.add_row("  vs homes-only (context, not the bar)", f"{f['auc_homes_only']:.4f}")
    t.add_row("lift over no-score", f"{f['auc_lift_vs_no_score']:+.4f}")
    t.add_row("Brier / log loss", f"{f['brier']:.4f} / {f['log_loss']:.4f}")
    t.add_row("calibration max decile gap", f"{f['calibration_max_gap']:.3f}")
    t.add_row("SHIPS", "[green]yes[/]" if f["ships"] else "[red]no[/]")
    console.print(t)
    console.print(f"[dim]{f['ships_reason']}[/]")

    c = Table(title="per category — support, model, out-of-sample AUC at fit time")
    for col in ("category", "dated openings in fit window", "model", "n", "rate", "AUC"):
        c.add_column(col, justify="right" if col != "category" else "left")
    for cat, r in sorted(f["by_category"].items(),
                         key=lambda kv: -kv[1].get("support_openings", 0)):
        if "skipped" in r:
            c.add_row(cat, f"{rep['support'].get(cat, 0):,}", "—",
                      f"{r['n']:,}", "—", r["skipped"])
            continue
        c.add_row(cat, f"{r['support_openings']:,}", r["model"], f"{r['n']:,}",
                  f"{r['positive_rate']:.1%}",
                  "—" if r["auc"] != r["auc"] else f"{r['auc']:.3f}")
    console.print(c)

    console.print("[yellow]This forecasts ENTRY, not viability (D88). A high "
                  "p_opening says the MARKET is likely to act near this doorway "
                  "-- and the retrodiction found entry going where supply was "
                  "already THICK, which is as consistent with herding into "
                  "saturated corridors as with agglomeration being real. "
                  "Nothing here separates them.[/]")


@forecast_app.command("score")
def forecast_score(
    issued_month: str = typer.Option(None, "--issued-month",
                                     help="The vintage to score, YYYY-MM. "
                                          "Omit to score every vintage whose "
                                          "horizon has elapsed."),
    as_of: str = typer.Option(None, "--as-of",
                              help="Right edge of the scoring window, YYYY-MM. "
                                   "Defaults to issue month + horizon."),
    model_version: str = typer.Option(None, "--model-version"),
    radius_m: float = typer.Option(400.0, "--radius-m"),
    dry_run: bool = typer.Option(False, "--dry-run"),
) -> None:
    """Score a vintage against what actually happened.

    OUTCOME: a same-category dated first-seen (source_date | gov_filing) in the
    principled supply set, within 400 m STRAIGHT-LINE -- the same radius, the
    same projection and the same ledger rule the features were frozen from, so
    the model and the thing it is judged against cannot drift apart. The window
    is half-open: [first day of the issue month, first day of --as-of).

    Scoring the same vintage at 12 and at 24 months writes TWO rows, not a
    correction of the first. A 24-month score looks better for a trivial reason
    -- a longer window -- and is labelled with its elapsed horizon.
    """
    from loci.model import forecast as fc

    say = lambda m: console.print(f"[dim]{m}[/]")       # noqa: E731
    if dry_run:
        con = fc.connect_read()
        try:
            reps = [fc.score(con, issued_month, as_of=as_of,
                             version=model_version, radius_m=radius_m,
                             dry_run=True, progress=say)]
        finally:
            con.close()
    else:
        reps = fc.score_managed(issued_month, as_of=as_of,
                                version=model_version, radius_m=radius_m,
                                progress=say)
    if not reps:
        console.print("[yellow]nothing due — no vintage has an elapsed horizon "
                      "without an outcome row.[/]")
        return

    for rep in reps:
        for v, s in rep["versions"].items():
            console.print(Panel.fit(
                f"vintage [bold]{rep['issued_month']}[/] · model {v}\n"
                f"scored as of {rep['scored_month']} "
                f"({s['horizon_elapsed']} months elapsed)\n"
                f"n {s['n']:,} · realized {s['realized_rate']:.1%} · "
                f"mean p {s['mean_p']:.3f}",
                title="forecast scored"))
            t = Table()
            t.add_column("measure"); t.add_column("value", justify="right")
            t.add_row("AUC", f"{s['auc']:.4f}")
            t.add_row("Brier", f"{s['brier']:.4f}")
            t.add_row("log loss", f"{s['log_loss']:.4f}")
            t.add_row("calibration max decile gap",
                      f"{s['calibration_max_gap']:.3f}")
            console.print(t)

            c = Table(title="by category")
            for col in ("category", "model", "n", "realized", "mean p", "AUC",
                        "Brier", "cal gap"):
                c.add_column(col, justify="right" if col != "category" else "left")
            for cat, r in sorted(s["by_category"].items(),
                                 key=lambda kv: -kv[1]["realized_rate"]):
                c.add_row(cat, r["support"], f"{r['n']:,}",
                          f"{r['realized_rate']:.1%}", f"{r['mean_p']:.3f}",
                          "—" if r["auc"] != r["auc"] else f"{r['auc']:.3f}",
                          f"{r['brier']:.4f}", f"{r['calibration_max_gap']:.3f}")
            console.print(c)

            d = Table(title="calibration deciles (out of sample by construction "
                            "-- the outcome did not exist at issue)")
            for col in ("decile", "n", "predicted", "observed"):
                d.add_column(col, justify="right")
            for row in s["calibration"]:
                d.add_row(str(row["decile"]), f"{row['n']:,}",
                          f"{row['predicted']:.3f}", f"{row['observed']:.3f}")
            console.print(d)


@forecast_app.command("report")
def forecast_report(
    issued_month: str = typer.Option(None, "--issued-month",
                                     help="Restrict the surprise tables to one "
                                          "vintage. Default: the newest scored."),
    scored_month: str = typer.Option(None, "--scored-month"),
    category: str = typer.Option("(all)", "--category",
                                 help="'(all)' is the roll-up across the 15."),
    top: int = typer.Option(10, "--top"),
    min_addresses: int = typer.Option(200, "--min-addresses"),
) -> None:
    """The track record, then the NTAs where the market surprised the model.

    Read-only. Everything printed is recomputed FROM THE LEDGER, never from a
    cached summary, so the table cannot drift from the stored rows.
    """
    import json

    from loci.model import forecast as fc

    con = fc.connect_read()
    fc.require_schema(con)

    runs = fc.runs(con)
    if len(runs):
        t = Table(title="vintages issued")
        for col in ("issued", "model", "fit rows", "NTAs", "AUC", "no-score",
                    "persist", "cal gap", "ships", "rows"):
            t.add_column(col, justify="right" if col not in ("issued", "model",
                                                             "ships") else "left")
        for _, r in runs.iterrows():
            cal = json.loads(r["calibration_json"] or "[]")
            gap = (max(abs(c["predicted"] - c["observed"]) for c in cal)
                   if cal else float("nan"))
            t.add_row(r["issued_month"], r["model_version"],
                      f"{int(r['n_fit_rows'] or 0):,}", str(r["n_fit_ntas"]),
                      f"{r['auc_blocked']:.4f}", f"{r['auc_no_score']:.4f}",
                      "—" if r["auc_persistence"] != r["auc_persistence"]
                      else f"{r['auc_persistence']:.4f}",
                      "—" if gap != gap else f"{gap:.3f}",
                      "[green]yes[/]" if r["ships"] else "[red]no[/]",
                      f"{int(r['n_rows_issued'] or 0):,}")
        console.print(t)

    tr = fc.track_record(con)
    if not tr:
        console.print("[yellow]No vintage has been scored yet. "
                      "`loci forecast score --issued-month YYYY-MM`.[/]")
        return

    t = Table(title="THE TRACK RECORD — every scored vintage, failures included")
    for col in ("vintage", "model", "scored", "months", "n", "realized",
                "mean p", "AUC", "Brier", "cal max gap"):
        t.add_column(col, justify="right" if col not in ("vintage", "model",
                                                          "scored") else "left")
    for row in tr:
        sc = fc.vintage_scores(con, row["issued_month"], row["scored_month"],
                               version=row["model_version"])
        s = sc.get(row["model_version"], {})
        t.add_row(row["issued_month"], row["model_version"], row["scored_month"],
                  str(int(row["horizon_elapsed"])), f"{int(row['n']):,}",
                  f"{row['realized_rate']:.1%}", f"{row['mean_p']:.3f}",
                  "—" if not s or s["auc"] != s["auc"] else f"{s['auc']:.4f}",
                  "—" if not s else f"{s['brier']:.4f}",
                  "—" if not s else f"{s['calibration_max_gap']:.3f}")
    console.print(t)

    im = issued_month or tr[-1]["issued_month"]
    sm = scored_month or tr[-1]["scored_month"]
    sur = fc.surprise_nta(con, im, sm, category=category, limit=top,
                          min_addresses=min_addresses)
    if len(sur):
        n_tests = int(con.execute(
            "SELECT count(*) FROM analysis.forecast_surprise_nta "
            "WHERE issued_month = ? AND scored_month = ? AND category = ? "
            "AND z_clustered IS NOT NULL", [im, sm, category]).fetchone()[0])
        # Bonferroni over the number of NTA statistics actually computed. A
        # "top 10 by z" list is a MAXIMUM over hundreds of statistics and will
        # contain |z| > 2 under the pure null; the threshold is printed so the
        # table is read as a ranking, not as a set of findings.
        from scipy.stats import norm as _norm
        thresh = (float(abs(_norm.ppf(0.05 / (2 * max(n_tests, 1)))))
                  if n_tests else float("nan"))

        sur = sur.sort_values("z_clustered", ascending=False)
        for label, part in (("POSITIVE surprise — the market did MORE than the "
                             "model expected", sur.head(top)),
                            ("NEGATIVE surprise — the market did LESS",
                             sur.tail(top).sort_values("z_clustered"))):
            t = Table(title=f"{label}  ({im} scored {sm}, category {category})")
            for col in ("NTA", "addresses", "cells", "realized", "expected",
                        "surprise", "z clustered", "z naive", "passes Bonferroni"):
                t.add_column(col, justify="right" if col != "NTA" else "left")
            for _, r in part.iterrows():
                t.add_row(str(r["nta_code"]), f"{int(r['n_addresses']):,}",
                          f"{int(r['n_cells']):,}", f"{r['realized']:.0f}",
                          f"{r['expected']:.0f}", f"{r['surprise']:+.0f}",
                          f"{r['z_clustered']:+.2f}", f"{r['z_naive']:+.2f}",
                          "yes" if abs(r["z_clustered"]) >= thresh else "no")
            console.print(t)
        console.print(f"[dim]{n_tests} NTA statistics computed; Bonferroni "
                      f"|z| threshold {thresh:.2f}. The z is CLUSTER-ROBUST on "
                      f"800 m cells because two addresses 150 m apart share "
                      f"nearly the same 400 m disc and are not two "
                      f"observations; `z naive` is the uncorrected version and "
                      f"the gap between them is the design effect.[/]")

    console.print("\n[yellow]PLAIN WORDS. This model forecasts ENTRY, not "
                  "viability (D88). A positive surprise means more doorways saw "
                  "a nearby opening than a model frozen beforehand expected -- "
                  "it says the four features miss something about that "
                  "neighbourhood, NOT that the openings there will succeed. "
                  "Loci has no identified business-level survival outcome: "
                  "every closure instrument in the warehouse is a current-state "
                  "extract, and the one premises-level test that IS identified "
                  "returns a null whose sign flips with the definition of "
                  "attrition.[/]")


@forecast_app.command("distribution")
def forecast_distribution(
    issued_month: str = typer.Option(..., "--issued-month"),
    model_version: str = typer.Option(None, "--model-version"),
) -> None:
    """What a vintage SAYS, before anything is known about whether it is right.

    p_opening quantiles per category. Read this beside the support column: a
    category predicted by the pooled model is carrying a slope estimated mostly
    on restaurants, and its p50 is an extrapolation, not a measurement.
    """
    from loci.model import forecast as fc

    con = fc.connect_read()
    fc.require_schema(con)
    df = fc.p_distribution(con, issued_month, version=model_version)
    t = Table(title=f"p_opening by category — vintage {issued_month}")
    for col in ("category", "model", "n", "p10", "p50", "p90", "max"):
        t.add_column(col, justify="right" if col != "category" else "left")
    for _, r in df.iterrows():
        t.add_row(r["category"], r["support"], f"{int(r['n']):,}",
                  f"{r['p10']:.3f}", f"{r['p50']:.3f}", f"{r['p90']:.3f}",
                  f"{r['pmax']:.3f}")
    console.print(t)


@forecast_app.command("prune")
def forecast_prune(
    keep_vintages: int = typer.Option(3, "--keep-vintages",
                                      help="Newest vintages per model_version "
                                           "whose PREDICTION rows survive."),
    dry_run: bool = typer.Option(
        None, "--dry-run/--no-dry-run",
        help="Print what would be pruned without deleting. Default: on, "
             "unless env var LOCI_FORECAST_PRUNE_REAL=1 is set (the "
             "`make chains-refresh` switch)."),
) -> None:
    """Retention for analysis.forecast (GTM-163) -- nothing bounded it before
    this, and one issue+score cycle adds ~1.4 GB.

    Deletes PREDICTION rows for vintages older than the newest
    --keep-vintages PER MODEL_VERSION. NEVER touches analysis.forecast_run
    (the fit diagnostics) or analysis.forecast_outcome (the scored track
    record) -- both are the ledger itself and survive every prune. NEVER a
    vintage whose 12-month horizon has not elapsed, and never one that has
    not actually been scored yet however old it is -- `forecast score` still
    needs to JOIN its rows in analysis.forecast to write outcomes.

    DRY RUN BY DEFAULT. This is a DELETE on the ledger's largest table
    running on a schedule; a retention rule that silently deletes evidence on
    its first bad day is worse than the disk growth it exists to fix. Pass
    --no-dry-run (or set LOCI_FORECAST_PRUNE_REAL=1, what
    `make chains-refresh` checks) to actually delete.

    After a real prune this runs CHECKPOINT and a best-effort VACUUM.
    NEITHER SHRINKS THE .duckdb FILE ON DISK -- verified empirically against
    this DuckDB build: CHECKPOINT flushes the WAL and marks the freed blocks
    reusable by future writes, VACUUM only recomputes statistics, and the
    file's byte size does not change either way. Actually shrinking the file
    needs a full rebuild (`EXPORT DATABASE` to a new file, or `ATTACH` a new
    file and `COPY FROM DATABASE current`) -- an offline, whole-database
    operation out of scope for a routine prune.
    """
    import os

    from loci.model import forecast as fc

    if dry_run is None:
        dry_run = os.environ.get("LOCI_FORECAST_PRUNE_REAL", "") != "1"

    say = lambda m: console.print(f"[dim]{m}[/]")       # noqa: E731
    if dry_run:
        con = fc.connect_read()
    else:
        con = fc.connect_write()
    try:
        rep = fc.prune(con, keep_vintages=keep_vintages, dry_run=dry_run,
                       progress=say)
    finally:
        con.close()

    t = Table(title="forecast prune"
                    + ("  [yellow](dry run — nothing deleted)[/]"
                       if rep["dry_run"] else ""))
    for col in ("issued_month", "model_version", "rows"):
        t.add_column(col, justify="right" if col == "rows" else "left")
    for r in rep["candidates"]:
        t.add_row(r["issued_month"], r["model_version"], f"{r['n_rows']:,}")
    if not rep["candidates"]:
        t.add_row("—", "—", "0")
    console.print(t)
    console.print(f"[bold]{rep['n_rows']:,}[/] rows "
                  + ("would be deleted" if rep["dry_run"] else "deleted")
                  + f", ~{rep['estimated_bytes_freed'] / 1e6:.1f} MB estimated "
                    f"(--keep-vintages {rep['keep_vintages']})")
    if rep["kept_open_horizon"]:
        console.print(
            f"[yellow]{len(rep['kept_open_horizon'])} vintage(s) kept despite "
            "ranking outside --keep-vintages: horizon not yet elapsed, or not "
            "yet scored.[/]")
    if not rep["dry_run"]:
        console.print(
            f"[dim]CHECKPOINT {'ok' if rep['checkpointed'] else 'skipped'} · "
            f"VACUUM {'ok' if rep['vacuumed'] else 'skipped'} -- neither "
            "shrinks the .duckdb FILE by itself; see this command's "
            "docstring.[/]")


# ---------------------------------------------------------------------------
# loci capacity -- carrying capacity (docs/carrying-capacity-2026-09.md)
# ---------------------------------------------------------------------------

@app.command("capacity")
def capacity_cmd(
    residents: float = typer.Option(None, "--residents", "-n",
                                    help="Catchment population."),
    density: float = typer.Option(None, "--density", "-d",
                                  help="Residents per km2 of the catchment."),
    category: str = typer.Option(None, "--category", "-c",
                                 help="One of the 15 slugs; default all."),
    fit: bool = typer.Option(False, "--fit",
                             help="Re-estimate and rewrite "
                                  "src/loci/model/carrying_capacity.yaml."),
    show: bool = typer.Option(False, "--show",
                              help="Print the fitted parameters per category."),
    boroughs: str = typer.Option("MN,BK", "--boroughs",
                                 help="Boroughs for the NYC half of a --fit."),
    bootstrap: int = typer.Option(None, "--bootstrap",
                                  help="NTA block-bootstrap draws (0 = skip)."),
    nyc_only: bool = typer.Option(False, "--nyc-only",
                                  help="With --fit: skip the national half "
                                       "(no Census pull)."),
    dry_run: bool = typer.Option(False, "--dry-run",
                                 help="With --fit: estimate and print, write nothing."),
) -> None:
    """How many establishments of each category coexist with N people at density D.

    THE ANSWER IS AN OBSERVED EQUILIBRIUM, NOT A CAPACITY. It says what New York
    HAS at this density in 2024-26, not what a market could hold and not what
    would survive: Loci has no viability outcome (D88), so no line of output here
    can be read as "there is room for one more".

    Three numbers ship side by side per category:

      expected      the NYC curve -- establishments within a 400 m NETWORK walk
                    of a doorway whose walkshed holds this many people. Catchments
                    overlap, so this is a SITE-LEVEL count, not a count of shops
                    "belonging to" those residents.
      national      the same category's establishments per 1,000 residents at
                    this density on the CBP/ZCTA curve fitted across every US
                    metro of 500k or more, with New York held out of the fit.
      cbp/poi       Loci's principled POI count divided by CBP payroll
                    establishments on the same NYC ZIP partition -- the unit
                    conversion between the two columns above, and a portability
                    parameter in its own right (a city without New York's licence
                    rosters will not reproduce it).

    `--fit` reads the warehouse READ ONLY (retrying a lock a concurrent writer
    holds) and writes nothing to it: the NYC curve lands in
    src/loci/model/carrying_capacity.yaml as package data and the Census pulls
    cache under data/raw/cbp/ and data/raw/zbp/. No analysis table is created or
    updated by this command, deliberately -- the fit is 15 rows of parameters,
    not a new grain.
    """
    from loci.categories import CATEGORIES
    from loci.model import carrying_capacity as cc

    if fit:
        bl = tuple(b.strip().upper() for b in boroughs.split(",") if b.strip())
        n_boot = cc.BOOTSTRAP_B if bootstrap is None else bootstrap
        con = cc.connect_read_only_retry()

        def prog(i, n, cat, rec):
            console.print(f"  [{i}/{n}] {cat}: [bold]{rec.get('form','—')}[/] "
                          f"({rec.get('fit_seconds','?')}s)")

        console.print(f"[bold]Fitting the NYC curve[/] on {','.join(bl)} lot rows "
                      f"(bootstrap {n_boot})")
        doc = (cc.run_fit(con, bl, n_boot, progress=prog) if nyc_only
               else cc.run_all(con, bl, n_boot, progress=prog))
        if dry_run:
            console.print("[yellow]--dry-run: nothing written[/]")
        else:
            path = cc.write_fit(doc)
            console.print(f"wrote [bold]{path}[/]  fit_hash {doc['fit_hash']}")
        _capacity_fit_table(doc)
        return

    if show:
        _capacity_fit_table(cc.load_fit())
        return

    if residents is None or density is None:
        raise typer.BadParameter(
            "give both --residents and --density (or use --fit / --show). "
            "Density is residents per km2 of the catchment; residents/density "
            "is the implied walkshed area, which is checked against the band "
            "the curve was estimated on.")
    if category and category not in CATEGORIES:
        raise typer.BadParameter(f"unknown category {category!r}; "
                                 f"one of {', '.join(CATEGORIES)}")

    rows = cc.capacity(residents, density, category)
    head, body = rows[0], rows[1:]

    console.print(f"\n[bold]{residents:,.0f} residents at "
                  f"{density:,.0f}/km²[/] — implied walkshed "
                  f"{head['implied_walkshed_km2']:.3f} km²"
                  + ("" if head["in_support_walkshed"]
                     else f"  [red](outside the {cc.SHED_KM2_SUPPORT[0]}–"
                          f"{cc.SHED_KM2_SUPPORT[1]} km² band the NYC curve was "
                          f"fitted on — the NYC column is an extrapolation)[/]"))

    t = Table(show_header=True, header_style="bold")
    for col, just in (("category", "left"), ("NYC expected", "right"),
                      ("90% CI", "right"), ("per 1k res", "right"),
                      ("national per 1k", "right"), ("NYC/nat'l", "right"),
                      ("CBP/POI", "right"), ("form", "left")):
        t.add_column(col, justify=just)
    for r in body:
        if not r.get("fitted"):
            t.add_row(r["category"], "—", "—", "—", "—", "—", "—",
                      f"[dim]{r.get('reason','not fitted')}[/]")
            continue
        ci = r.get("ci90")
        mark = "" if r["in_support_residents"] else " [red]*[/]"
        t.add_row(r["category"],
                  f"{r['expected']:.1f}{mark}",
                  "—" if not ci else f"{ci[0]:.1f}–{ci[1]:.1f}",
                  f"{r['per_1000_residents']:.2f}",
                  "—" if r["national_per_1000_residents"] is None
                  else f"{r['national_per_1000_residents']:.3f}",
                  "—" if r["nyc_vs_national_ratio"] is None
                  else f"{r['nyc_vs_national_ratio']:.2f}×",
                  "—" if r["cbp_per_poi_ratio"] is None
                  else f"{r['cbp_per_poi_ratio']:.2f}×",
                  f"{r['form']} [dim]({r['shape']})[/]")
    t.caption = ("* = this resident count is outside the 1st–99th percentile of "
                 "MN+BK walksheds, so the NYC number is extrapolated. The shape in "
                 "brackets is read off the fitted elasticity at the top of the "
                 "observed range, not off the form's name: `accelerating` means each "
                 "extra 1,000 residents buys MORE shops than the last.")
    console.print(t)
    console.print(f"\n[yellow]{head['caveat']}[/]")
    console.print("[dim]NYC expected counts POIs within a 400 m walk and catchments "
                  "overlap, so it is not comparable to the national per-1,000 column "
                  "without the CBP/POI conversion; `proportional` means the gate "
                  "refused every curved form and the fit is a straight line through "
                  "the origin.[/]")


def _capacity_fit_table(doc: dict) -> None:
    """The fitted parameters, the gate's verdict, and both reconciliations."""
    t = Table(title="NYC carrying capacity — fitted forms (400 m walkshed, MN+BK)",
              show_header=True, header_style="bold")
    for col, just in (("category", "left"), ("form / shape", "left"),
                      ("e(res|area) p10→p90", "right"), ("e(area|res)", "right"),
                      ("per 1k @p50", "right"), ("flattens at", "right"),
                      ("gain vs base", "right"), ("D70", "left"),
                      ("cap-bound", "right")):
        t.add_column(col, justify=just)
    for cat, r in (doc.get("categories") or {}).items():
        if not r.get("fitted"):
            t.add_row(cat, "[dim]not fitted[/]", "—", "—", "—", "—", "—", "—", "—")
            continue
        e = r["elasticity_at"]
        gain = max((v.get("deviance_gain_vs_baseline", 0.0)
                    for k, v in r["cv"].items() if k == r["form"]), default=0.0)
        cb = r.get("capacity_bound_share")
        t.add_row(
            cat,
            f"{r['form']} [dim]{r['shape']}[/]",
            f"{e['p10']['residents_fixed_area']:.2f}→"
            f"{e['p90']['residents_fixed_area']:.2f}",
            f"{e['p50']['area_fixed_residents']:+.2f}",
            f"{r['estab_per_1000_residents_at']['p50']:.2f}",
            "—" if r["flatten_residents"] is None
            else f"{r['flatten_residents']:,.0f} res "
                 f"({r['flatten_density_residents_km2']:,.0f}/km²)",
            f"{gain:+.1%}",
            r.get("d70_regime") or "—",
            # NaN check without importing math into this module: a float is NaN
            # iff it is not equal to itself, and ruff's self-comparison warning
            # is silenced explicitly rather than by restructuring the guard.
            "—" if cb is None or cb != cb else f"{cb:.0%}")  # noqa: PLR0124
    t.caption = ("e(res|area) = d log(establishments)/d log(residents) with the "
                 "walkshed area held fixed: 1.00 is constant-per-capita, below 1 is "
                 "saturation, above 1 means supply grows FASTER than population. "
                 "e(area|res) > 0 means shops scale with land (frontage) as well as "
                 "with customers. D70 is the 2013–23 GROWTH regime at ZIP grain — a "
                 "different estimand, shown for comparison, not agreement. cap-bound "
                 "is D91's PLUTO floor-area ceiling share.")
    console.print(t)

    nat = doc.get("national") or {}
    if nat:
        u = doc.get("national_universe", {})
        t = Table(title=f"National CBP curve — {u.get('n_zctas','?'):,} ZCTAs in "
                        f"{u.get('n_metros','?')} metros ≥500k, NYC held out",
                  show_header=True, header_style="bold")
        for col, just in (("category", "left"), ("form", "left"),
                          ("per 1k @ nat'l p50", "right"), ("@ p90", "right"),
                          ("NYC observed/1k", "right"), ("NYC predicted/1k", "right"),
                          ("NYC ratio", "right"), ("strict-universe ratio", "right")):
            t.add_column(col, justify=just)
        for cat, r in nat.items():
            if not r.get("fitted"):
                t.add_row(cat, "[dim]not fitted[/]", "—", "—", "—", "—", "—", "—")
                continue
            h = r.get("held_out_metro") or {}
            sens = r.get("sensitivity_cbp_presence_only") or {}
            ratio = h.get("ratio_observed_over_predicted")
            colour = ("green" if ratio and ratio >= 1.5
                      else "red" if ratio and ratio <= 0.67 else "")
            t.add_row(cat, r["form"],
                      f"{r['rate_per_1000_at']['p50']:.3f}",
                      f"{r['rate_per_1000_at']['p90']:.3f}",
                      "—" if not h else f"{h['observed_per_1000']:.3f}",
                      "—" if not h else f"{h['predicted_per_1000']:.3f}",
                      "—" if ratio is None
                      else (f"[{colour}]{ratio:.2f}×[/]" if colour else f"{ratio:.2f}×"),
                      "—" if not sens
                      else f"{sens['nyc_ratio_observed_over_predicted']:.2f}×")
        t.caption = ("NYC ratio = observed CBP establishments in NYC's 765 ZCTAs "
                     "divided by what the national curve predicts at their densities. "
                     "Above 1 = NYC carries more of this category than its density "
                     "explains. The strict column drops the 1,775 ZCTAs with no CBP "
                     "presence in any of the 15 categories.")
        console.print(t)

    near = doc.get("nearest_metros") or []
    if near:
        t = Table(title="NYC's nearest metros on the carrying-capacity surface",
                  show_header=True, header_style="bold")
        for col in ("metro", "population", "pop-weighted density", "distance"):
            t.add_column(col, justify="right" if col != "metro" else "left")
        for r in near:
            t.add_row(r["cbsa_name"], f"{r['population']:,.0f}",
                      f"{r['weighted_density']:,.0f}/km²",
                      f"{r['distance_to_target']:.2f}")
        t.caption = ("distance = Euclidean on z-scored log(pop-weighted density) plus "
                     "the log per-1,000 rate of all 15 categories — similar RETAIL MIX "
                     "at similar density, not merely similar size")
        console.print(t)

    ratios = doc.get("cbp_poi_ratio") or {}
    if ratios:
        t = Table(title="CBP-to-POI bridge on the NYC ZIP partition "
                        "(principled supply set)",
                  show_header=True, header_style="bold")
        for col, just in (("category", "left"), ("Loci POIs", "right"),
                          ("CBP estab", "right"), ("aggregate ratio", "right"),
                          ("median ZIP ratio", "right")):
            t.add_column(col, justify=just)
        for cat, r in sorted(ratios.items()):
            t.add_row(cat, f"{r['poi_principled']:,.0f}", f"{r['cbp_estab']:,.0f}",
                      "—" if r["ratio_aggregate"] is None
                      else f"{r['ratio_aggregate']:.2f}×",
                      "—" if r["ratio_median_zip"] is None
                      else f"{r['ratio_median_zip']:.2f}×")
        t.caption = ("CBP counts PAYROLL establishments and Loci counts POIs, so a "
                     "ratio above 1 is mostly sole proprietors CBP never sees plus the "
                     "D47 dedup residual, and below 1 is Loci coverage. This ratio is "
                     "itself the portability parameter: a second city reproduces it "
                     "only as well as it reproduces NYC's licence rosters.")
        console.print(t)


# ---------------------------------------------------------------------------
# loci colocation -- two businesses at one address, and whether one closed
# (owner ask 2026-09-14; defect GTM-153, cause D36/GTM-121)
# ---------------------------------------------------------------------------

@app.command(name="colocation")
def colocation(
    supply_set: str = typer.Option("principled", "--supply-set",
                                   help="all | principled | corroborated"),
    category: str = typer.Option(None, "--category",
                                 help="restrict the per-group detail to one category"),
    collapse_unresolved: bool = typer.Option(
        False, "--collapse-unresolved",
        help="ALSO show the set with unresolved co-located groups collapsed to one "
             "row each. Never applied to the warehouse; the module default stays OFF "
             "pending an owner ruling."),
    emit_sql: bool = typer.Option(
        False, "--emit-sql",
        help="print the generated DDL for sql/029_poi_colocation.sql and exit"),
    examples: int = typer.Option(0, "--examples",
                                 help="print N resolved groups as worked evidence"),
):
    """Co-located same-category POIs, by resolution, and what the closure gate costs.

    READ-ONLY: opens the warehouse read_only and runs only SELECTs. The gate
    itself lives in score/supply.canonical_poi_sql (GATE_CLOSED, default ON);
    this command only reports it, and `--collapse-unresolved` only PRICES the
    alternative -- it changes nothing.
    """
    from loci.model.poi_presence import (COORD_DP, OPEN_EVIDENCE_MAX_AGE_DAYS,
                                         colocation_view_sql)
    from loci.model.recommend import connect_read_only
    from loci.score.supply import (COLLAPSE_UNRESOLVED, GATE_CLOSED, canonical_poi_sql,
                                   colocation_report)

    if emit_sql:
        print(colocation_view_sql())
        raise typer.Exit(0)

    con = connect_read_only(retries=8, wait_s=30.0)
    try:
        df, tot = colocation_report(con, supply_set)

        t = Table(title=f"Co-located same-category groups — {supply_set} supply set",
                  show_header=True, header_style="bold")
        for col, just in (("category", "left"), ("canonical", "right"),
                          ("closed", "right"), ("gated", "right"),
                          ("groups", "right"), ("one_closed", "right"),
                          ("all_closed", "right"), ("both_open", "right"),
                          ("unresolved", "right"), ("collapse −", "right")):
            t.add_column(col, justify=just)
        for r in df.sort_values("n_canonical", ascending=False).to_dict("records"):
            t.add_row(r["category"], f"{r['n_canonical']:,}",
                      f"[red]{r['n_closed']:,}[/]" if r["n_closed"] else "0",
                      f"{r['n_gated']:,}", f"{r['n_groups']:,}",
                      f"{r['groups_one_closed']:,}", f"{r['groups_all_closed']:,}",
                      f"{r['groups_both_open']:,}",
                      f"[yellow]{r['groups_unresolved']:,}[/]"
                      if r["groups_unresolved"] else "0",
                      f"{r['n_collapse_would_drop']:,}")
        t.caption = (
            f"'closed' = the predicate's EVIDENCED closures only (a ledger closed_on "
            f"or a source-published status); 'unknown' is never gated. Groups are "
            f"exact-coordinate ({COORD_DP} dp ≈ 1 m) and PER CATEGORY. "
            f"'collapse −' is what --collapse-unresolved WOULD remove; it is OFF "
            f"(COLLAPSE_UNRESOLVED={COLLAPSE_UNRESOLVED}) because a large building "
            f"legitimately holds two restaurants at one geocode.")
        console.print(t)

        n_ungated = con.execute(
            "SELECT count(*) FROM (" +
            canonical_poi_sql(supply_set, "s.poi_id", gate_closed=False) + ")"
        ).fetchone()[0]
        n_gated = con.execute(
            "SELECT count(*) FROM (" +
            canonical_poi_sql(supply_set, "s.poi_id", gate_closed=True) + ")"
        ).fetchone()[0]
        console.print(
            f"\n[bold]supply count[/]  ungated {n_ungated:,}  →  gated {n_gated:,}  "
            f"([red]−{n_ungated - n_gated:,}[/], "
            f"{100 * (n_ungated - n_gated) / max(n_ungated, 1):.2f}%)   "
            f"GATE_CLOSED={GATE_CLOSED}, open-evidence window "
            f"{OPEN_EVIDENCE_MAX_AGE_DAYS} d")
        console.print(
            f"[bold]co-location blast radius[/]  {tot['n_colocated']:,} of "
            f"{tot['n_canonical']:,} canonical POIs "
            f"({100 * tot['share_affected']:.2f}%) sit in a same-category "
            f"co-located group; {tot['groups_unresolved']:,} groups "
            f"({tot['n_unresolved_poi']:,} POIs) the published evidence cannot split.")

        if collapse_unresolved:
            n_collapsed = con.execute(
                "SELECT count(*) FROM (" +
                canonical_poi_sql(supply_set, "s.poi_id", gate_closed=True,
                                  collapse_unresolved=True) + ")").fetchone()[0]
            console.print(
                f"[bold]--collapse-unresolved[/]  would be {n_collapsed:,} "
                f"([yellow]−{n_gated - n_collapsed:,}[/] further, "
                f"{100 * (n_gated - n_collapsed) / max(n_gated, 1):.2f}%). "
                "NOT APPLIED — this is the alternative, priced, pending an owner "
                "ruling.")

        # How often a published DOHMH verdict is what splits a restaurant pair --
        # the D36 question, asked of the data rather than assumed.
        cat = category or "restaurant"
        d = con.execute(f"""
            WITH s AS (SELECT * FROM analysis.poi_supply_status
                       WHERE {_supply_col(supply_set)} AND category = ?),
            g AS (SELECT colocation_key, count(*) AS n_poi,
                         any_value(colocation_resolution) AS res,
                         count(*) FILTER (WHERE poi_status_basis LIKE 'nyc_dohmh%'
                                            AND poi_status <> 'unknown') AS n_dohmh,
                         count(*) FILTER (WHERE poi_status_basis LIKE '%:stale\\_%'
                                                ESCAPE '\\') AS n_stale,
                         count(*) FILTER (WHERE poi_status = 'open') AS n_open
                  FROM s GROUP BY 1 HAVING count(*) >= 2)
            SELECT count(*) AS groups,
                   count(*) FILTER (WHERE res <> 'unresolved') AS resolved,
                   count(*) FILTER (WHERE res <> 'unresolved' AND n_dohmh > 0)
                       AS resolved_with_dohmh,
                   count(*) FILTER (WHERE res = 'unresolved' AND n_stale > 0
                                      AND n_open > 0) AS stale_vs_open
            FROM g""", [cat]).fetchone()
        if d and d[0]:
            console.print(
                f"\n[bold]{cat}[/]  {d[0]:,} co-located groups; {d[1]:,} resolved "
                f"({100 * d[1] / d[0]:.1f}%), {d[2]:,} of those with a published "
                f"DOHMH verdict among the members ({100 * d[2] / d[0]:.1f}% of all "
                f"groups). {d[3]:,} unresolved groups pair a DOHMH 'stale_*' record "
                "with a positively-open one — the D36 turnover signature, which D79 "
                "refuses to call a closure because it is derived from the ABSENCE of "
                "a recent inspection, not from anything DOHMH published.")

        if examples:
            rows = con.execute("""
                SELECT category, group_key, n_poi, resolution, evidence
                FROM analysis.poi_colocation
                WHERE resolution = 'one_closed'
                  AND (? IS NULL OR category = ?)
                ORDER BY n_poi, group_key LIMIT ?
            """, [category, category, examples]).fetchall()
            for c, key, n, res, ev in rows:
                console.print(f"\n[bold]{c}[/] {key}  n={n}  {res}")
                console.print(f"  {ev}")
    finally:
        con.close()
    raise typer.Exit(0)


def _supply_col(supply_set: str) -> str:
    from loci.score.supply import supply_predicate
    return supply_predicate(supply_set)


# ===========================================================================
# Citi Bike (phase 1, owner-approved 2026-09-14). Appended at the END of this
# file on purpose: two other sessions hold uncommitted blocks above, and
# appending is the only edit that cannot collide with them.
# ===========================================================================

citibike_app = typer.Typer(add_completion=False, help=(
    "Citi Bike trip data: the first TWO-DIRECTIONAL movement series in the "
    "warehouse.\n\n"
    "Subway entries (D76) publish only the morning tap-IN and read zero for 65% "
    "of Brooklyn addresses. A bike trip publishes a start AND an end, and the "
    "dock network reaches Bay Ridge, Greenpoint and Red Hook. `ends` are dated "
    "by the ARRIVAL time, which is what makes bike_ends_400m the first "
    "arrival-side measure here.\n\n"
    "CARD CONTEXT ONLY, on the D76 footing: nothing built from this enters "
    "gap_score, supply_ratio_vs_base or any recommendation grade. Dock "
    "placement is an operator's capital plan and is correlated with income, so "
    "a zero is a statement about the network, never about the sidewalk."))
app.add_typer(citibike_app, name="citibike")


def _cb_connect(db: "Path | None" = None, read_only: bool = False,
                retries: int = 60, wait_s: float = 30.0):
    """Open the warehouse, waiting out another builder's write lock.

    Several sessions rebuild analysis.address concurrently in this project, and
    a DuckDB file has ONE writer. Failing instantly on a lock would turn a
    30-minute ingest into a coin flip, so this retries with a stated wait
    instead of racing.

    The budget is DELIBERATELY LONG (30 minutes by default): the thing most
    likely to hold the lock here is a full screen rebuild, which takes tens of
    minutes, and a 3-minute budget would mean every ingest launched during one
    fails. Waiting is cheap; a half-ingested panel is not.
    """
    import time as _time

    last = None
    for attempt in range(retries):
        try:
            return locidb.connect(db, read_only=read_only)
        except Exception as exc:  # noqa: BLE001 - duckdb raises IOException
            if "lock" not in str(exc).lower():
                raise
            last = exc
            console.print(f"[dim]database locked by another session; retrying in "
                          f"{wait_s:.0f}s ({attempt + 1}/{retries})…[/]")
            _time.sleep(wait_s)
    raise typer.BadParameter(
        f"the warehouse stayed locked for {retries} attempts ({last}). Another "
        f"builder is holding the write lock; re-run when it finishes.")


def _cb_month(spec: str) -> "tuple[int, int]":
    try:
        y, m = spec.replace("/", "-").split("-")[:2]
        return int(y), int(m)
    except Exception:  # noqa: BLE001
        raise typer.BadParameter(f"month must be YYYY-MM, got {spec!r}") from None


@citibike_app.command("ingest")
def citibike_ingest(
    start: str = typer.Option("2023-01", "--start", help="First month, YYYY-MM."),
    end: str = typer.Option(None, "--end",
                            help="Last month, YYYY-MM. Default: the latest month "
                                 "the BUCKET publishes (not today's date -- a "
                                 "month's file lands days into the next one)."),
    resume: bool = typer.Option(True, "--resume/--no-resume",
                                help="Skip months already in the table. This is "
                                     "what makes an interrupted 25 GB run cheap "
                                     "to restart."),
    refresh: bool = typer.Option(False, "--refresh",
                                 help="Re-fetch the bucket listing."),
    keep_csv: bool = typer.Option(False, "--keep-csv",
                                  help="Leave the extracted CSVs on disk (debug; "
                                       "~4 GB per month)."),
    db: Path = typer.Option(None, "--db", help="Warehouse path (default: data/loci.duckdb)."),
    dry_run: bool = typer.Option(False, "--dry-run", help="Read and check; write nothing."),
) -> None:
    """Download, extract and aggregate Citi Bike trips into staging.

        staging.citibike_station_month   one row per dock per month per
                                         day_type per daypart
        staging.citibike_station         the dock roster, with first/last month

    ONE MONTH IS THE UNIT OF WORK AND OF IDEMPOTENCE. Its CSVs are extracted,
    aggregated, written and deleted before the next month is touched, so peak
    disk is one month (~4 GB) rather than the ~25 GB the window would be, and a
    re-run of March cannot rewrite April.

    FAIL LOUD. A month missing a calendar date raises (the divisor comes from
    the CALENDAR, so a half-published month would otherwise be divided by a full
    one); a month under the trip floor raises; a pre-2021 header raises with its
    reason rather than being mapped onto the modern station-id space; a dock
    outside the New York bounding box raises (a Jersey City file leaked in).
    """
    from loci.sources.cities.nyc import citibike as cb

    con = _cb_connect(db, read_only=dry_run)
    if not dry_run:
        locidb.init_schema(con)
    try:
        def _tick(a: dict) -> None:
            if "skipped" in a:
                console.print(f"[dim]{a['month']}  skipped ({a['skipped']})[/]")
                return
            console.print(
                f"[green]{a['month']}[/]  {a['rows_in_file']:,} trips · "
                f"{a['stations']:,} docks · {a['cells']:,} cells · "
                f"{a['starts']:,} starts / {a['ends']:,} ends · "
                f"{a['days_by_type']['weekday']} weekdays · "
                f"{a['dockless_starts']:,} dockless starts, "
                f"{a['end_events_after_month_end']:,} arrivals past month end")

        report = cb.ingest(con, _cb_month(start),
                           _cb_month(end) if end else None,
                           refresh=refresh, dry_run=dry_run,
                           keep_csv=keep_csv, skip_existing=resume,
                           on_month=_tick)
        console.print(
            f"\nwindow [bold]{report['start']}..{report['end']}[/] · "
            f"{report['months']} months planned · "
            f"{report['months_ingested']} ingested · "
            f"{report['bytes'] / 1e9:.1f} GB of zips · "
            f"{report['trips_in_files']:,} trips read")
        console.print(
            f"excluded: {report['dockless_starts']:,} dockless starts / "
            f"{report['dockless_ends']:,} dockless ends (no dock to attribute) · "
            f"{report['end_events_after_month_end']:,} arrivals past the file's "
            f"month end (the month is the unit of idempotence -- see the module "
            f"docstring)")
        if report.get("dates_with_no_trip"):
            console.print(
                f"[yellow]{report['dates_with_no_trip']} calendar date(s)[/] carried "
                f"NO trip system-wide ({', '.join(report['months_with_a_zero_date'])}) "
                f"— a system outage, e.g. a storm, not a missing file: the file's "
                f"last date is the month's last date. They STAY in the divisor, "
                f"because an average weekday that month really did include a day "
                f"the docks were shut, and dropping days because ridership was low "
                f"would select on the outcome.")
        if dry_run:
            console.print("[dim]--dry-run:[/] nothing written.")
            raise typer.Exit(0)
        console.print(f"[green]ok[/] {report['rows_written']:,} rows -> "
                      f"staging.citibike_station_month · "
                      f"{report['stations']:,} docks -> staging.citibike_station")

        t = Table(title="validation — staging.citibike_station_month")
        cols = ("month", "cells", "stations", "starts", "ends", "start_end_gap_pct",
                "distinct_cells", "weekdays")
        for c in cols:
            t.add_column(c, justify="left" if c == "month" else "right")
        df = con.execute(cb.VALIDATION_SQL).fetchdf()
        for r in df.tail(14).to_dict("records"):
            t.add_row(str(r["month"])[:7] if r["month"] is not None else "ALL",
                      f"{int(r['cells']):,}", f"{int(r['stations']):,}",
                      f"{int(r['starts']):,}", f"{int(r['ends']):,}",
                      f"{r['start_end_gap_pct']:+.2f}%"
                      if r["start_end_gap_pct"] is not None else "-",
                      str(int(r["distinct_cells"])), str(int(r["weekdays"] or 0)))
        console.print(t)
        console.print(
            "[dim]start_end_gap_pct is starts minus ends over starts. Every trip "
            "is one start and one end inside the system, so the gap is only the "
            "dockless rides and the month-boundary spill; a large gap means a "
            "dropped part file or a station-id problem.[/]")
    finally:
        con.close()


@citibike_app.command("stats")
def citibike_stats(
    db: Path = typer.Option(None, "--db", help="Warehouse path."),
    compare: str = typer.Option("2023-01,2025-08", "--compare",
                                help="Two months, YYYY-MM,YYYY-MM, for the "
                                     "dock-count change."),
) -> None:
    """What the panel actually contains. READ-ONLY."""
    from loci.sources.cities.nyc import citibike as cb   # noqa: F401  (vocabulary)

    con = _cb_connect(db, read_only=True)
    try:
        tot = con.execute("""
            SELECT count(DISTINCT month) AS months, min(month) AS first_month,
                   max(month) AS last_month, count(DISTINCT station_id) AS stations,
                   sum(starts) AS starts, sum(ends) AS ends,
                   sum(member_starts) AS member_starts,
                   sum(casual_starts) AS casual_starts
            FROM staging.citibike_station_month""").fetchone()
        if not tot or tot[0] == 0:
            console.print("[red]staging.citibike_station_month is empty[/] — run "
                          "`loci citibike ingest`.")
            raise typer.Exit(1)
        months, first, last, stations, starts, ends, mem, cas = tot
        span = (last.year - first.year) * 12 + (last.month - first.month) + 1
        console.print(
            f"[bold]{months}[/] months {first:%Y-%m}..{last:%Y-%m} "
            f"({'CONTIGUOUS' if months == span else f'[red]{span - months} MISSING[/]'}) · "
            f"[bold]{stations:,}[/] distinct docks · "
            f"[bold]{starts:,}[/] starts / {ends:,} ends")
        console.print(
            f"member {mem:,} ({100 * mem / max(mem + cas, 1):.1f}%) · "
            f"casual {cas:,} ({100 * cas / max(mem + cas, 1):.1f}%) "
            f"[dim](of starts; a member holds a subscription and a casual rider a "
            f"single ride or day pass — NOT resident vs visitor)[/]")

        t = Table(title="seasonality — trips per average WEEKDAY by month "
                        "(starts + ends, holidays excluded)")
        for c, j in (("month", "left"), ("docks", "right"), ("weekdays", "right"),
                     ("starts/wd", "right"), ("ends/wd", "right"),
                     ("casual %", "right"), ("evening+wknd end %", "right")):
            t.add_column(c, justify=j)
        rows = con.execute("""
            WITH d AS (SELECT month, any_value(days_in_cell) AS days
                       FROM staging.citibike_station_month
                       WHERE day_type = 'weekday' GROUP BY 1)
            SELECT m.month, count(DISTINCT m.station_id) AS docks, d.days,
                   sum(m.starts) FILTER (m.day_type = 'weekday') / d.days AS s_wd,
                   sum(m.ends)   FILTER (m.day_type = 'weekday') / d.days AS e_wd,
                   100.0 * sum(m.casual_starts) / nullif(sum(m.starts), 0) AS cas,
                   100.0 * sum(m.ends) FILTER (m.daypart = 'evening'
                        OR m.day_type IN ('saturday', 'sunday'))
                        / nullif(sum(m.ends), 0) AS ev
            FROM staging.citibike_station_month m JOIN d USING (month)
            GROUP BY m.month, d.days ORDER BY m.month""").fetchdf()
        for r in rows.to_dict("records"):
            t.add_row(f"{r['month']:%Y-%m}", f"{int(r['docks']):,}",
                      str(int(r["days"])), f"{r['s_wd']:,.0f}", f"{r['e_wd']:,.0f}",
                      f"{r['cas']:.1f}%", f"{r['ev']:.1f}%")
        console.print(t)

        try:
            a, b = [x.strip() for x in compare.split(",")]
        except ValueError:
            raise typer.BadParameter("--compare wants YYYY-MM,YYYY-MM") from None
        cmp_rows = con.execute("""
            SELECT strftime(month, '%Y-%m') AS m,
                   count(DISTINCT station_id) AS docks, sum(starts) AS starts
            FROM staging.citibike_station_month
            WHERE strftime(month, '%Y-%m') IN (?, ?) GROUP BY 1 ORDER BY 1""",
            [a, b]).fetchdf()
        if len(cmp_rows) == 2:
            lo, hi = cmp_rows.to_dict("records")
            console.print(
                f"\n[bold]dock count[/] {lo['m']} {int(lo['docks']):,} → "
                f"{hi['m']} {int(hi['docks']):,} "
                f"([green]+{int(hi['docks'] - lo['docks']):,}[/], "
                f"{100 * (hi['docks'] - lo['docks']) / max(lo['docks'], 1):+.1f}%); "
                f"starts {int(lo['starts']):,} → {int(hi['starts']):,} "
                f"({100 * (hi['starts'] - lo['starts']) / max(lo['starts'], 1):+.1f}%)")
            console.print(
                "[dim]a dock counted in a month is a dock with at least one trip "
                "that month, so this is the ACTIVE network, not the installed one.[/]")
        else:
            console.print(f"[yellow]--compare[/] {a} and/or {b} are not in the panel.")
    finally:
        con.close()


@citibike_app.command("address-measures")
def citibike_address_measures(
    boroughs: str = typer.Option("MN,BK", help="Comma-separated borough codes, or ALL."),
    radius_m: float = typer.Option(400.0, "--radius-m",
                                   help="Catchment radius in NETWORK metres."),
    window_months: int = typer.Option(12, "--window-months",
                                      help="How many of the panel's latest months "
                                           "to pool. 12 covers a full seasonal "
                                           "cycle; Citi Bike's seasonality is far "
                                           "larger than the subway's."),
    re_sweep: bool = typer.Option(False, "--re-sweep",
                                  help="Force the Dijkstra sweep even when "
                                       "analysis.address_bike_station already "
                                       "covers the scope. Needed after a new walk "
                                       "graph, a changed radius, and after "
                                       "`loci address-gaps` (which destroys the rows)."),
    db: Path = typer.Option(None, "--db", help="Warehouse path (use a snapshot copy "
                                               "to prove a run without taking the "
                                               "live write lock)."),
    dry_run: bool = typer.Option(False, "--dry-run", help="Compute and print; write nothing."),
) -> None:
    """Walkable Citi Bike activity at address grain (LOT frame).

        analysis.address_bike_station     the persisted reachable dock set
        analysis.address.bike_starts_400m / bike_ends_400m
        analysis.address.bike_evening_ends_share_400m
        analysis.address.bike_casual_share_400m

    Same walk graph, same Dijkstra, same 400 m NETWORK radius as
    `loci transit-profile` -- `catchment_pairs` is imported from it, not
    re-implemented. The only difference is that the target points are docks.

    ZERO IS A VALUE (owner rule 2026-09-13, no eligibility gate): every lot
    address in scope gets a level, and 0 means "no dock within a five-minute
    walk" -- a statement about the operator's network, never about the sidewalk.
    The two SHARES are NULL where their denominator is zero, because a share of
    no arrivals does not exist and a 0 would assert a pure commuter dock at a
    place with no dock at all.

    THE SWEEP RUNS ONCE. `analysis.address_bike_station` persists
    (address_id, station_id, dist_m) so a different window or a distance-decay
    kernel is a JOIN, not another hour of Dijkstra.

    Run AFTER `loci address-gaps`; re-run with --re-sweep after any address
    rebuild (`bike_run_at IS NULL` is the flag).
    """
    from loci.model import address_bike as ab

    boros = _parse_boroughs(boroughs)
    con = _cb_connect(db, read_only=dry_run)
    if not dry_run:
        locidb.init_schema(con)
    try:
        reach = None if re_sweep else ab.load_reachable(con, boros)
        if reach is not None:
            console.print(f"[dim]reusing analysis.address_bike_station: "
                          f"{len(reach):,} (address, dock) pairs — no Dijkstra.[/]")
        else:
            console.print("[dim]no persisted reachable set for this scope; sweeping "
                          "the walk graph (the slow path, tens of minutes)…[/]")

        meas, reach, report = ab.build_address_bike(
            con, boros, radius_m=radius_m, window_months=window_months,
            reachable=reach, dry_run=dry_run)

        p = report["panel"]
        console.print(
            f"window [bold]{report['window']}[/] · {p['months']} months · "
            f"{p['weekday_days']} non-holiday weekdays · {p['stations']:,} docks · "
            f"{p['weekday_starts']:,} weekday starts / {p['weekday_ends']:,} ends")
        console.print(
            f"{report['addresses_with_a_station']:,} lot addresses have >=1 dock "
            f"within {report['radius_m']:.0f} m network "
            f"({report['pairs']:,} pairs, source: {report['source']}); every other "
            f"in-scope address is 0.0 — a measurement, not a gap")
        if report.get("docks_not_in_the_reachable_set"):
            console.print(
                f"[yellow]{report['docks_not_in_the_reachable_set']} docks[/] are in "
                f"the window but not in the persisted reachable set — installed "
                f"since the last sweep. They carry "
                f"{100 * report['share_of_weekday_starts_unswept']:.2f}% of the "
                f"window's weekday starts and every address near them UNDER-counts "
                f"by that much. Re-run with [bold]--re-sweep[/] to fix.")

        t = Table(title=f"walkable Citi Bike activity — {','.join(boros)} "
                        f"@ {report['radius_m']:.0f} m network "
                        f"(addresses with >=1 dock only)")
        for c, j in (("measure", "left"), ("n", "right"), ("p50", "right"),
                     ("p90", "right"), ("max", "right")):
            t.add_column(c, justify=j)
        for col in ("bike_starts_400m", "bike_ends_400m",
                    "bike_evening_ends_share_400m", "bike_casual_share_400m"):
            v = meas[col].dropna()
            dp = 3 if col.endswith("share_400m") else 1
            t.add_row(col, f"{len(v):,}", f"{v.median():,.{dp}f}",
                      f"{v.quantile(0.9):,.{dp}f}", f"{v.max():,.{dp}f}")
        console.print(t)

        if dry_run:
            console.print("[dim]--dry-run:[/] nothing written.")
            raise typer.Exit(0)
        w = report["_written"]
        console.print(f"[green]ok[/] {w['address_bike_station_rows']:,} rows -> "
                      f"analysis.address_bike_station · "
                      f"{w['addresses_with_a_station']:,} addresses measured · "
                      f"{w['addresses_zeroed']:,} in-scope addresses read 0")

        v = Table(title="validation — analysis.address (lot frame)")
        for c in ("borough", "lot_addresses", "measured", "with_a_dock",
                  "coverage_pct", "zero_starts", "impossible_nonzero",
                  "impossible_share", "p50_starts", "p90_starts", "p50_ends",
                  "p50_evening_share", "p50_casual_share"):
            v.add_column(c, justify="left" if c == "borough" else "right")
        for r in con.execute(ab.VALIDATION_SQL).fetchdf().to_dict("records"):
            v.add_row(str(r["borough"] or "ALL"),
                      *[("-" if r[c] is None else f"{r[c]:,}")
                        for c in ("lot_addresses", "measured", "with_a_dock",
                                  "coverage_pct", "zero_starts",
                                  "impossible_nonzero", "impossible_share",
                                  "p50_starts", "p90_starts", "p50_ends",
                                  "p50_evening_share", "p50_casual_share")])
        console.print(v)
        console.print("[dim]impossible_nonzero and impossible_share must both be 0: "
                      "an address with no reachable dock cannot have a positive "
                      "level or a defined share.[/]")
    finally:
        con.close()


@citibike_app.command("export")
def citibike_export(
    out: Path = typer.Option(None, "--out",
                             help="Output directory (default: webmap/data)."),
    window_months: int = typer.Option(12, "--window-months"),
    db: Path = typer.Option(None, "--db", help="Warehouse path."),
) -> None:
    """Write `webmap/data/bike.json` — docks sized by weekday starts.

    A STANDALONE FILE. It does not touch `viz/webmap_export.py`,
    `webmap/index.html` or `webmap/server.js`, which other threads own; wiring
    the layer in later is a fetch plus a toggle. Until then the file is inert.
    """
    from loci.viz import bike_export as bx

    con = _cb_connect(db, read_only=True)
    try:
        rep = bx.export(con, out_dir=out, window_months=window_months)
    finally:
        con.close()
    console.print(f"[green]ok[/] {rep['stations']:,} docks · window "
                  f"{rep['window']} · {rep['bytes'] / 1024:.0f} KB -> {rep['path']}")
    console.print("[dim]the payload carries its own caveats block; render it "
                  "UNTRUNCATED wherever the layer is switched on — 2,300 dots "
                  "sized by volume is exactly where 'no dot' gets read as 'no "
                  "activity', and a dock is where the operator put one.[/]")


@app.command(name="validate-bike")
def validate_bike(
    radius_m: float = typer.Option(400.0, "--radius-m", help="Catchment radius, NETWORK metres."),
    months: int = typer.Option(3, "--months", help="Ridership months to average."),
    window_months: int = typer.Option(12, "--window-months", help="Bike months to pool."),
    with_transit: bool = typer.Option(True, "--with-transit/--no-transit",
                                      help="Also sweep transit/jobs/homes for "
                                           "comparison (adds a graph load)."),
    out: Path = typer.Option(None, "--out", help="Write the per-point table to this CSV."),
    db: Path = typer.Option(None, "--db", help="Warehouse path."),
) -> None:
    """External check: do walkable BIKE flows rank real sidewalk volume?

    At each NYC DOT Bi-Annual Pedestrian Count screenline (the 100 ON-STREET
    points; `loc` 101-114 are bridge midpoints and are excluded), recompute
    Citi Bike starts + ends per average weekday within the radius, per daypart,
    and report Spearman rho against the observed count -- beside
    `transit_entries_400m` and `homes_400m` on the same points.

    THE OFF-DIAGONAL IS THE TEST. D76 got rho +0.79 overall for transit and
    then found the AM count was ranked BETTER by pm_peak than by am_peak, which
    demoted the measure to card context. The same comparison runs here: if the
    AM count is ranked as well by the evening bike flow as by the morning one,
    the daypart split carries no time-of-day information.

    READ-ONLY. Writes nothing to the warehouse; no score reads the result.
    """
    from loci.validation import bike_counts as bc

    con = _cb_connect(db, read_only=True)
    try:
        console.print("[dim]reading DOT counts + sweeping the walk graph…[/]")
        df, report = bc.run_validation(con, radius_m=radius_m, months=months,
                                       window_months=window_months,
                                       with_transit=with_transit)
    finally:
        con.close()

    console.print(f"round [bold]{report['round']}[/] · {report['on_street_points']} "
                  f"on-street points ({report['dropped_bridge_points']} bridge "
                  f"points excluded) · bike window {report['window']} · "
                  f"{report['stations']:,} docks · radius {report['radius_m']:.0f} m")

    t = Table(title="Spearman rho vs DOT observed whole-round count (AM+MD+PM)")
    for c, j in (("measure", "left"), ("rho (all)", "right"), ("N", "right"),
                 ("rho (Brooklyn)", "right"), ("N", "right")):
        t.add_column(c, justify=j)
    for k, v in report["correlations"].items():
        t.add_row(k, f"{v['spearman_rho']:+.3f}", str(v["n"]),
                  f"{v['spearman_rho_bk']:+.3f}", str(v["n_bk"]))
    console.print(t)

    t2 = Table(title="Per-window: each DOT count window vs the BIKE daypart that "
                     "contains it")
    for c, j in (("DOT window", "left"), ("hours", "left"), ("daypart", "left"),
                 ("bike rho", "right"), ("N", "right"), ("bike rho (BK)", "right"),
                 ("N", "right"), ("transit rho", "right"),
                 ("best off-diagonal", "left")):
        t2.add_column(c, justify=j)
    for win, v in report["by_window"].items():
        off = {k: r for k, r in v["off_diagonal"].items() if k != v["daypart"]}
        best = max(off, key=lambda k: off[k]) if off else "-"
        t2.add_row(win.upper(),
                   f"{v['dot_window_hours'][0]:02d}-{v['dot_window_hours'][1]:02d}",
                   v["daypart"], f"{v['spearman_rho']:+.3f}", str(v["n"]),
                   f"{v['spearman_rho_bk']:+.3f}", str(v["n_bk"]),
                   f"{v.get('transit_rho', float('nan')):+.3f}",
                   f"{best} {off.get(best, float('nan')):+.3f}")
    console.print(t2)
    console.print("[dim]if the AM count is ranked as well by the evening daypart as "
                  "by am_peak, the split carries no time-of-day information and the "
                  "number is a 'busy corridor' flag with extra steps — the finding "
                  "that demoted transit in D76.[/]")

    c = Table(title="coverage — share of LOT addresses within the radius of a dock "
                    "vs a subway entrance")
    for col in ("borough", "lot_addresses", "with_a_dock", "dock_pct",
                "with_an_entrance", "entrance_pct", "dock_only"):
        c.add_column(col, justify="left" if col == "borough" else "right")
    for r in report["coverage"].to_dict("records"):
        c.add_row(str(r["borough"] or "ALL"),
                  *[("-" if r[k] is None else f"{r[k]:,}")
                    for k in ("lot_addresses", "with_a_dock", "dock_pct",
                              "with_an_entrance", "entrance_pct", "dock_only")])
    console.print(c)
    console.print(f"[yellow]{report['points_with_zero_bike']} of {report['points']}[/] "
                  f"count points have bike = 0 — a tie block, which is where a rank "
                  f"correlation hides")
    console.print("[dim]DOT counts WEEKDAYS, so the saturday and sunday cells have "
                  "no counterpart and are explicitly UNVALIDATED. And note that DOT "
                  "points and Citi Bike docks are BOTH sited on busy commercial "
                  "corridors by two organisations optimising for related things: a "
                  "correlation between them is partly a correlation between two "
                  "siting policies.[/]")
    if out:
        df.to_csv(out, index=False)
        console.print(f"[green]ok[/] per-point table -> {out}")


# ===========================================================================
# loci poi-keys -- migrating the first-seen ledger across a key-recipe change
# ===========================================================================
poi_keys_app = typer.Typer(add_completion=False, help=(
    "Carry analysis.poi_presence across a change to the location_key recipe.\n\n"
    "`location_key` is a CONTENT HASH THAT INCLUDES THE CATEGORY "
    "(model/poi_presence.mint_key), so any change to the category rule re-mints "
    "keys -- and a re-minted key is indistinguishable from a NEW STOREFRONT to "
    "the ledger. The owner's category-precedence ruling 'B' (2026-09-14, a finer "
    "food category wins) moves ~4,363 keys and drops ~15,700; snapshotting that "
    "with no migration writes 4,363 fake openings and 15,700 fake "
    "disappearances, PERMANENTLY, because first_seen_month is write-once "
    "(sql/018).\n\n"
    "THE SEQUENCE, and it is not optional:\n"
    "  loci dedup  ->  loci poi-keys plan  ->  loci poi-keys apply\n"
    "              ->  loci poi-snapshot   ->  loci check-presence\n\n"
    "`loci poi-snapshot` calls the guard itself and REFUSES to run when the key "
    "sets have drifted without an applied map. Read sql/035_poi_key_map.sql."))
app.add_typer(poi_keys_app, name="poi-keys")


def _poi_keys_con(db: str | None, read_only: bool = False):
    """Resolve the warehouse the SAME way for read and write paths.

    LOCI_DB IS RESOLVED HERE, EXPLICITLY, and that is a scar. `db.connect()`
    honours $LOCI_DB only when it is passed no path at all, while
    `poi_presence.connect_write()` defaults to `db.DEFAULT_PATH` and therefore
    IGNORES $LOCI_DB entirely. So `LOCI_DB=/tmp/scratch.duckdb loci poi-keys
    apply` silently migrated the LIVE warehouse instead of the scratch copy --
    the read-only `guard` obeyed the variable and the writer did not, which is
    the worst possible split. Prefer `--db`; this makes $LOCI_DB work too."""
    import os as _os

    from loci.model import poi_presence as pp

    target = db or _os.environ.get("LOCI_DB") or str(locidb.DEFAULT_PATH)
    if read_only:
        from loci.model.recommend import connect_read_only
        return connect_read_only(target)
    return pp.connect_write(target)


@poi_keys_app.command("plan")
def poi_keys_plan(
    dry_run: bool = typer.Option(False, "--dry-run",
                                 help="Compute and print; write no map rows."),
    db: str = typer.Option(None, "--db", help="Warehouse path (default data/loci.duckdb). "
                                              "Use a scratch copy to rehearse."),
    show: int = typer.Option(12, "--show", help="Category transitions to list."),
) -> None:
    """Diff the CURRENT dedup's minted keys against the ledger and write the map.

    Reads `analysis.poi_dedup` + `staging.poi` (the same query `poi-snapshot`
    uses, deliberately -- two definitions of "the locations the ledger is
    about" is how a migration plans against a different universe than the
    snapshot writes), mints the key each cluster WOULD get, and classifies
    every ledger key the new dedup no longer mints:

      relabel_poi  one old key -> one FREE new key, found via the ledger
                   row's canonical/member poi_id in analysis.poi_dedup. The
                   dedup's own assertion of identity; the strongest route.
      relabel_loc  the same, found via name + 4 dp coordinate because the
                   ledger row had no live poi_id. Good enough to relabel.
      merged       two or more contributing ledger rows -> one new key, all on
                   the poi route. THE TARGET MAY ALREADY BE HELD by a surviving
                   ledger row, and usually is (4,538 of 8,134 groups on the
                   live B-rule plan) -- that row is folded IN, not overwritten.
                   The survivor keeps the EARLIEST first_seen and its kind, the
                   LATEST last_seen, max(n_months_seen) (never the sum), min
                   ledger_started_month, and the union of the closure columns.
      unmapped   genuinely gone. NEVER DELETED, never rewritten: the row keeps
                 last_seen_month at the previous month, exactly as an ordinary
                 disappearance does. The map row is the audit that we looked.
      collision  a CONTENT-route candidate refused -- its target is already
                 held, contested, or its content matched more than one new
                 cluster. A name + 4 dp cell match is evidence of a
                 relabelling, never evidence that two storefronts are one
                 business, so nothing is done.

    On a warehouse whose dedup has not changed this reports zero candidates.
    That no-op IS the useful result: it says the ledger and the dedup agree."""
    from loci.model import poi_key_migration as km

    con = _poi_keys_con(db)
    try:
        res = km.plan(con, dry_run=dry_run)
    except (ValueError, RuntimeError) as exc:
        console.print(f"[red]FAIL[/] {exc}")
        raise typer.Exit(1) from exc
    finally:
        pass

    t = Table(title="poi-keys plan" + (" — DRY RUN, nothing written" if dry_run else ""))
    t.add_column("metric"); t.add_column("n", justify="right")
    t.add_row("deduped locations (current)", f"{res.n_dedup:,}")
    t.add_row("ledger rows", f"{res.n_ledger:,}")
    t.add_row(f"  seen in the newest month", f"{res.n_ledger_current:,}")
    t.add_row("ledger keys the dedup still mints", f"{res.n_surviving:,}")
    t.add_row("ledger keys ABSENT from the dedup", f"{res.n_absent:,}"
              + (f"  ({100 * res.absent_pct:.2f}%)" if res.n_ledger_current else ""))
    t.add_row("[green]relabel_poi[/] 1:1 via canonical poi_id",
              f"{res.relabel_poi:,}")
    t.add_row("[green]relabel_loc[/] 1:1 via name + 4 dp coord",
              f"{res.relabel_loc:,}")
    t.add_row("[green]merged[/] groups", f"{res.merged_groups:,}")
    t.add_row("  old keys folded in", f"{res.merged_old_keys:,}")
    t.add_row("  ... into a key a ledger row already held",
              f"{res.merged_into_existing:,}")
    t.add_row("[yellow]unmapped[/] (gone; left alone)", f"{res.unmapped:,}")
    t.add_row("[red]collision[/] (refused)", f"{res.collisions:,}")
    t.add_row("new keys, no old key behind them", f"{res.new_keys:,}")
    console.print(t)

    if res.by_transition and show:
        tt = Table(title="category transitions")
        tt.add_column("old -> new"); tt.add_column("n", justify="right")
        for k, v in sorted(res.by_transition.items(), key=lambda kv: -kv[1])[:show]:
            tt.add_row(k, f"{v:,}")
        console.print(tt)

    if res.by_route:
        rt = Table(title="match route")
        rt.add_column("route"); rt.add_column("n", justify="right")
        for k, v in sorted(res.by_route.items(), key=lambda kv: -kv[1]):
            rt.add_row(k, f"{v:,}")
        console.print(rt)

    if not res.mapped and not res.merged_groups:
        console.print("[green]ok[/] no keys to migrate — the ledger and the "
                      "current dedup agree. `loci poi-snapshot` is safe to run.")
    elif dry_run:
        console.print("[yellow]DRY RUN[/] — re-run without --dry-run to write "
                      "analysis.poi_key_map, then `loci poi-keys apply`.")
    else:
        console.print(f"[green]ok[/] wrote {res.written:,} rows to "
                      "analysis.poi_key_map. Next: [bold]loci poi-keys apply[/], "
                      "then [bold]loci poi-snapshot[/].")
    if res.collisions:
        console.print("[red]NOTE[/] collisions are recorded and REFUSED, not "
                      "applied. They need a human: `SELECT * FROM "
                      "analysis.poi_key_map WHERE reason = 'collision'`.")
    raise typer.Exit(0)


@poi_keys_app.command("apply")
def poi_keys_apply(
    dry_run: bool = typer.Option(False, "--dry-run",
                                 help="Report what would move; write nothing."),
    db: str = typer.Option(None, "--db", help="Warehouse path."),
) -> None:
    """Rewrite location_key everywhere it is stored, in ONE transaction.

    Acts on the newest plan that still has unapplied mapped/merged rows, and
    rewrites: `analysis.poi_presence` (preserving first_seen_month, kind,
    src_date/field, closed_on/src and n_months_seen), `chains.brand_location`
    (de-duplicating the (month, brand, key) primary key a merge can break),
    `analysis.recommendation_outcome.matched_location_key`,
    `staging.poi_closure` and `analysis.poi_closure_evidence`.

    THE CATEGORY MOVES WITH THE KEY. That is not cosmetic: the snapshot's
    pass-A match tests the key AND the category, so a row whose key was
    rewritten but whose category was not would still mint a fresh key next
    month -- the exact fake opening this exists to prevent.

    Idempotent three ways over: the map row is stamped `applied_at`, a
    rewritten old key no longer exists to be matched, and a second call finds
    no pending plan and does nothing."""
    from loci.model import poi_key_migration as km

    con = _poi_keys_con(db)
    try:
        res = km.apply(con, dry_run=dry_run)
    except (ValueError, RuntimeError) as exc:
        console.print(f"[red]FAIL[/] {exc}")
        raise typer.Exit(1) from exc

    if res.noop:
        console.print("[green]ok[/] nothing to apply — no plan has unapplied "
                      "mapped/merged rows. (Idempotent: this is what a second "
                      "`apply` looks like.)")
        raise typer.Exit(0)

    t = Table(title="poi-keys apply"
                    + (" — DRY RUN, nothing written" if res.dry_run else ""))
    t.add_column("metric"); t.add_column("n", justify="right")
    t.add_row("plan", str(res.planned_at))
    t.add_row("ledger rows re-keyed (1:1)", f"{res.n_rows_migrated:,}")
    t.add_row("  via canonical poi_id", f"{res.n_relabel_poi:,}")
    t.add_row("  via name + 4 dp coordinate", f"{res.n_relabel_loc:,}")
    t.add_row("merge groups", f"{res.n_merged_groups:,}")
    t.add_row("  into a key a ledger row already held",
              f"{res.n_merged_into_existing:,}")
    t.add_row("  rows folded away by merges", f"{res.n_merged_absorbed:,}")
    t.add_row("unmapped (recorded, untouched)", f"{res.n_unmapped:,}")
    t.add_row("collisions (recorded, refused)", f"{res.n_collisions:,}")
    t.add_row("ledger rows before", f"{res.ledger_before:,}")
    t.add_row("ledger rows after", f"{res.ledger_after:,}")
    for table, info in sorted(res.dependents.items()):
        t.add_row(f"  {table}", ", ".join(f"{k}={v}" for k, v in info.items()))
    console.print(t)
    if not res.dry_run:
        console.print("[green]ok[/] next: [bold]loci poi-snapshot[/] then "
                      "[bold]loci check-presence[/].")
    raise typer.Exit(0)


@poi_keys_app.command("guard")
def poi_keys_guard(
    month: str = typer.Option(None, "--month", help="Month to look for a map in; "
                                                    "default the current month."),
    threshold: float = typer.Option(None, "--threshold",
                                    help="Absent-key fraction that trips the guard "
                                         "(default 0.005)."),
    db: str = typer.Option(None, "--db", help="Warehouse path."),
) -> None:
    """Refuse (exit 1) if the dedup's key set has drifted from the ledger's.

    `loci poi-snapshot` calls this itself, so running it separately is belt and
    braces for the monthly job — `make chains-refresh` runs it immediately
    before the snapshot so the job fails on the guard rather than halfway
    through a write.

    It compares the keys the CURRENT dedup would mint against the ledger rows
    seen in the newest snapshot month (not the whole ledger, which accumulates
    genuinely-departed rows forever and would trip this permanently). Over
    0.5% absent and it refuses, unless every mapped/merged row planned in the
    month has been applied.

    HONEST ABOUT ITS OWN REACH: it measures exact-hash misses only. The
    snapshot's name+40 m link pass rescues some of them, so a trip OVERSTATES
    the damage — it is a demand that a human look at `loci poi-keys plan`, not
    a proof of corruption. It cannot see the reverse mistake at all (a key that
    stayed but whose meaning changed)."""
    from loci.model import poi_key_migration as km

    con = _poi_keys_con(db, read_only=True)
    kw = {"month": month}
    if threshold is not None:
        kw["threshold"] = threshold
    try:
        stats = km.guard_snapshot(con, **kw)
    except km.KeyDriftError as exc:
        console.print(f"[red]REFUSE[/] {exc}")
        raise typer.Exit(1) from exc
    except RuntimeError as exc:
        console.print(f"[red]FAIL[/] {exc}")
        raise typer.Exit(1) from exc

    if stats.get("bypass"):
        console.print(f"[green]ok[/] guard passed (bypass: {stats['bypass']})")
    else:
        console.print(
            f"[green]ok[/] {stats['n_absent']:,} of {stats['n_ledger_current']:,} "
            f"ledger keys from {stats['newest_month']} absent from the dedup "
            f"({100 * stats['absent_pct']:.3f}%, threshold "
            f"{100 * stats['threshold']:.2f}%); {stats['n_new']:,} keys are new.")
    raise typer.Exit(0)


@app.command("report")
def report_cmd(
    address: str = typer.Argument(
        ..., help="A Loci address_id, or free text geocoded via NYC Planning "
                  "Labs GeoSearch and snapped to the address frame."),
    dry_run: bool = typer.Option(
        False, "--dry-run", help="Print the planned paid calls and estimated "
                                 "cost; spend nothing."),
    no_cache: bool = typer.Option(
        False, "--no-cache", help="Skip the 30-day cache read (still writes "
                                  "a fresh cache entry when it runs)."),
    closure_checks: bool = typer.Option(
        True, "--closure-checks/--no-closure-checks",
        help="Plan and make on-demand Places/web closure checks for unknown "
            "POIs in the catchment (default: on). --no-closure-checks makes "
            "zero closure-check calls and writes zero closure-evidence rows; "
            "the Supply section still lists every POI's current status and "
            "basis, and the rents/leases/news searches and prose call still run."),
    cap: float = typer.Option(1.0, "--cap", help="Hard spend cap in USD."),
    out: str = typer.Option(
        None, "--out", help="Write the markdown here instead of "
                            "docs/recommendations/<slug>-<date>.md."),
    db: str = typer.Option(None, "--db", help="Warehouse path."),
) -> None:
    """Generate (or fetch from cache) the allocator memo for one address
    (D100, GTM-172, seed AC-14..AC-22).

    `address` is either an existing Loci `address_id` or free text resolved
    through `loci.geo.geosearch.resolve` (GeoSearch, then a BBL or <=50 m
    snap to the address frame) -- an address GeoSearch cannot place, or that
    snaps to nothing in coverage, is refused with 'not in Loci coverage'
    (exit 2), never a degraded report (seed "Search rule").
    """
    from loci.geo.geosearch import NotInCoverage, resolve
    from loci.report.run import generate

    con = locidb.connect(db, read_only=dry_run)
    try:
        address_id = resolve(con, address)
    except NotInCoverage as exc:
        console.print(f"[red]{exc}[/]")
        raise typer.Exit(2) from exc

    result = generate(con, address_id, cap_usd=cap, dry_run=dry_run,
                      no_cache=no_cache, out=out, closure_checks=closure_checks)

    if dry_run:
        if result.plan:
            t = Table(title="loci report --dry-run — planned calls")
            t.add_column("provider"); t.add_column("detail")
            t.add_column("usd", justify="right")
            for call in result.plan:
                t.add_row(call.provider, call.detail or "", f"${call.usd:.3f}")
            console.print(t)
        console.print(f"[green]ok[/] dry run — estimated ${result.total_usd:.3f}, "
                      f"zero paid calls, run_id={result.run_id}")
        raise typer.Exit(0)

    console.print(f"[green]ok[/] {result.path}  ${result.total_usd:.3f}  "
                  f"run_id={result.run_id}"
                  + ("  (cached)" if result.cached else ""))
    raise typer.Exit(0)


# ===========================================================================
# loci verify-closures -- budget-capped closure checks for 'unknown' POIs
# (D98, GTM-170, AC-11). Core logic (Budget / select_unknown / verify) lives
# in evidence/verify.py and is tested there directly with fakes; this wrapper
# only parses args, resolves a bbox, builds the two PAID clients LAZILY (never
# for --dry-run -- see verify()'s own docstring: "budget, con and the two
# clients are not touched at all in that branch"), and prints the result.
# Appended at the END of this file on purpose: other sessions hold
# uncommitted blocks above (poi-keys, citibike, `report` just above this one)
# and appending is the only edit that cannot collide with theirs.
# ===========================================================================

@app.command(name="verify-closures")
def verify_closures_cmd(
    budget: float = typer.Option(
        ..., "--budget", help="Hard USD cap for this run. evidence.verify."
                              "Budget.reserve() refuses the call that would cross it -- "
                              "never rounds or averages past the cap."),
    bbox: str = typer.Option(
        None, "--bbox", help="minlon,minlat,maxlon,maxlat. Exactly one of "
                             "--bbox/--area is required: select_unknown() never runs "
                             "citywide unbudgeted (design constraint)."),
    area: str = typer.Option(
        None, "--area", help="Neighborhood name, ILIKE-matched against "
                             "analysis.address_gaps.neighborhood; its envelope becomes "
                             "the bbox."),
    dry_run: bool = typer.Option(
        False, "--dry-run", help="Print the candidate plan and its estimated cost. "
                                 "Makes ZERO paid calls, ZERO writes, and constructs "
                                 "neither GooglePlacesClient nor TavilyWebSearch."),
    limit: int = typer.Option(
        None, "--limit", help="Cap the number of candidate POIs selected, largest "
                              "co-located group first."),
    recheck_days: int = typer.Option(
        30, "--recheck-days", help="Skip a POI whose newest closure evidence was "
                                   "retrieved within this many days."),
    supply_set: str = typer.Option(
        "principled", "--supply-set", help="all | principled | corroborated"),
    poi: list[str] = typer.Option(
        None, "--poi", help="Restrict candidates to this poi_id. Repeatable. "
                            "Composes with --bbox/--area (still required)."),
    name: str = typer.Option(
        None, "--name", help="Restrict candidates to POIs whose name contains this "
                             "substring, case-insensitive."),
    db: str = typer.Option(None, "--db", help="Warehouse path."),
) -> None:
    """Budget-capped closure checks for canonical POIs still reading
    poi_status = 'unknown', inside a bbox or a named neighborhood (D98,
    GTM-170).

    Places first, web fallback, per POI -- see evidence/verify.py's module
    docstring for the reserve -> ledger row -> call -> evidence-row sequence
    and why a run that hits `--budget` stops cleanly mid-POI rather than
    half-spending on one. `--dry-run` runs the SAME selection query and
    prints the SAME plan a real run would spend against, so the two can never
    silently disagree about what a run would do. `--poi`/`--name` narrow the
    candidate set for a targeted re-check without giving up the bbox/area
    requirement.
    """
    from loci.evidence.verify import Budget, area_bbox, select_unknown, verify

    if bool(bbox) == bool(area):
        console.print("[red]FAIL[/] pass exactly one of --bbox or --area.")
        raise typer.Exit(1)

    con = locidb.connect(db, read_only=dry_run)
    try:
        if bbox:
            parts = [p.strip() for p in bbox.split(",")]
            if len(parts) != 4:
                console.print("[red]FAIL[/] --bbox needs 4 comma-separated numbers: "
                              "minlon,minlat,maxlon,maxlat.")
                raise typer.Exit(1)
            try:
                box = tuple(float(p) for p in parts)
            except ValueError as exc:
                console.print(f"[red]FAIL[/] --bbox values must be numbers: {exc}")
                raise typer.Exit(1) from exc
        else:
            try:
                box = area_bbox(con, area)
            except ValueError as exc:
                console.print(f"[red]FAIL[/] {exc}")
                raise typer.Exit(1) from exc

        cands = select_unknown(con, bbox=box, supply_set=supply_set,
                               recheck_days=recheck_days, limit=limit,
                               poi_ids=list(poi) if poi else None, name=name)
        bgt = Budget(usd=budget)

        if dry_run:
            result = verify(con, cands, budget=bgt, places=None, web=None, dry_run=True)
            t = Table(title=f"verify-closures --dry-run — {len(cands)} candidate POIs "
                            f"in {'--bbox' if bbox else f'--area {area!r}'}")
            t.add_column("poi_id"); t.add_column("name"); t.add_column("category")
            t.add_column("co-located", justify="right")
            for c in cands:
                t.add_row(c.poi_id, c.name, c.category, str(c.colocation_n))
            console.print(t)
            console.print(
                f"[bold]plan[/]  {len(result.plan)} planned calls (places first, web "
                f"fallback per POI) — estimated ${result.estimated_usd:.3f} against a "
                f"${budget:.2f} cap. ZERO calls made, ZERO rows written — dry-run "
                "constructed neither paid client.")
            raise typer.Exit(0)

        # LAZY, and ONLY here: a dry-run must never construct either paid client.
        from loci.evidence.web_search import TavilyWebSearch
        from loci.validation.google_places import GooglePlacesClient

        places = GooglePlacesClient()
        web = TavilyWebSearch()
        result = verify(con, cands, budget=bgt, places=places, web=web, dry_run=False)
    finally:
        con.close()

    t = Table(title=f"verify-closures  run_id={result.run_id}")
    t.add_column("metric"); t.add_column("n", justify="right")
    t.add_row("candidates selected", f"{len(cands):,}")
    t.add_row("checked", f"{result.checked:,}")
    t.add_row("places calls", f"{result.places_calls:,}")
    t.add_row("web calls", f"{result.web_calls:,}")
    t.add_row("closed", f"[red]{result.closed}[/]" if result.closed else "0")
    t.add_row("opened", f"{result.opened:,}")
    t.add_row("still unknown", f"{result.still_unknown:,}")
    t.add_row("budget hit", "[yellow]yes[/]" if result.budget_hit else "no")
    console.print(t)
    console.print(f"[bold]spend[/]  ${result.spent_usd:.3f} of ${budget:.2f} cap "
                  f"(run_id={result.run_id})")
    raise typer.Exit(0)


# ===========================================================================
# Citi Bike phase 2 -- OD leakage (GTM-167, owner rulings R1/R2/R3 2026-09-15).
# Appended at the END of this file for the same reason the phase 1 block was:
# other sessions hold uncommitted hunks above, and appending is the only edit
# that cannot collide with them. `od-measures` and `od-validate` (the model
# side) land after this block.
# ===========================================================================

def _od_require_table(con) -> None:
    """Refuse to run before sql/037 has been renamed out of `.draft`.

    037_citibike_od.sql.draft is deliberately invisible to `db.init_schema`'s
    `*.sql` glob: that function runs on EVERY write connection, so an undrafted
    migration goes live on a peer session's next write and moves the shared
    supply hash (D105/D106, GTM-179). The rename is the lead's call, announced
    first. Until then this command must say so rather than raise a bare
    "Catalog Error: Table with name bike_od_leakage does not exist".
    """
    got = con.execute(
        "SELECT count(*) FROM information_schema.tables "
        "WHERE table_schema = 'analysis' AND table_name = 'bike_od_leakage'"
    ).fetchone()[0]
    if not got:
        raise typer.BadParameter(
            "analysis.bike_od_leakage does not exist. The migration is still "
            "src/loci/sql/037_citibike_od.sql.draft — the .draft suffix keeps it "
            "out of db.init_schema's glob so it cannot go live on a peer "
            "session's write and move the shared supply hash. Rename it to "
            "037_citibike_od.sql (announce the migration to the other sessions "
            "first) and re-run.")


@citibike_app.command("od-ingest")
def citibike_od_ingest(
    start: str = typer.Option("2023-01", "--start", help="First month, YYYY-MM."),
    end: str = typer.Option(None, "--end",
                            help="Last month, YYYY-MM. Default: the latest month "
                                 "the BUCKET publishes."),
    resume: bool = typer.Option(True, "--resume/--no-resume",
                                help="Skip months already in "
                                     "analysis.bike_od_leakage. This is what makes "
                                     "an interrupted multi-hour run cheap to "
                                     "restart."),
    refresh: bool = typer.Option(False, "--refresh",
                                 help="Re-fetch the bucket listing."),
    keep_csv: bool = typer.Option(False, "--keep-csv",
                                  help="Leave the extracted CSVs on disk (debug; "
                                       "~4 GB per month)."),
    db: Path = typer.Option(None, "--db",
                            help="Warehouse path (default: data/loci.duckdb)."),
    dry_run: bool = typer.Option(False, "--dry-run",
                                 help="Read, check and time; write nothing."),
) -> None:
    """Aggregate Citi Bike trips into ORIGIN NTA x DESTINATION NTA leakage cells.

        analysis.bike_od_leakage   origin_nta x destination_nta x month x
                                   day_type x daypart x origin_type

    PHASE 1 MUST HAVE THE MONTH FIRST. `origin_type` (R2) and the dock -> NTA
    geography are both derived from staging.citibike_station_month, so a month
    absent from that panel RAISES rather than typing every dock 'unknown' and
    quietly emptying the residential class the leakage view reads.

    ONE MONTH IS THE UNIT OF WORK AND OF IDEMPOTENCE, exactly as in phase 1: its
    CSVs are extracted, aggregated, written and deleted before the next month is
    touched, and a re-run of March cannot rewrite April.

    A TRIP IS DATED BY ITS DEPARTURE here, unlike `ends` in phase 1, which are
    dated by the arrival. The origin is what this table partitions on, and
    origin-side dating is what makes an OD cell reconcile to phase 1's `starts`.

    CARD CONTEXT ONLY under D76 (R1): nothing built from this enters gap_score,
    supply_ratio_vs_base, any recommendation grade, or the revenue lambda.
    """
    from loci.sources.cities.nyc import citibike_od as cbod

    con = _cb_connect(db, read_only=dry_run)
    try:
        if not dry_run:
            locidb.init_schema(con)
        _od_require_table(con)

        def _tick(a: dict) -> None:
            if "skipped" in a:
                console.print(f"[dim]{a['month']}  skipped ({a['skipped']})[/]")
                return
            ot = a["origin_types"]
            console.print(
                f"[green]{a['month']}[/]  {a['od_trips']:,} od trips · "
                f"{a['cells']:,} cells · {a['nta_pairs']:,} NTA pairs · "
                f"{a['round_trip_share']:.2%} round · docks "
                f"{ot['residential']}R/{ot['mixed']}M/{ot['destination']}D/"
                f"{ot['unknown']}U · {a['dock_nta']['unmapped']} unmapped · "
                f"unzip {a['unzip_s']}s + agg {a['aggregate_s']}s + "
                f"write {a['write_s']}s")

        report = cbod.ingest_od(con, _cb_month(start),
                                _cb_month(end) if end else None,
                                refresh=refresh, dry_run=dry_run,
                                keep_csv=keep_csv, skip_existing=resume,
                                on_month=_tick)
        console.print(
            f"\nwindow [bold]{report['start']}..{report['end']}[/] · "
            f"{report['months']} months planned · "
            f"{report['months_ingested']} ingested · "
            f"{report['trips_in_files']:,} trips read · "
            f"{report['od_trips']:,} dock-to-dock · "
            f"{report['seconds']:.0f}s")
        console.print(
            f"excluded: {report['dropped_dockless_end']:,} dockless ends "
            f"(no dock to attribute) · {report['dropped_out_of_system']:,} ends on "
            f"another operator's dock or a shop id · "
            f"{report['trips_dropped_unmapped_dock']:,} trips on a dock with no "
            f"cell in analysis.hex. Round trips ({report['round_trips']:,}) are "
            f"KEPT, in their own column: they carry no destination and the view "
            f"subtracts them.")
        if dry_run:
            console.print("[dim]--dry-run:[/] nothing written.")
            raise typer.Exit(0)
        console.print(f"[green]ok[/] {report['rows_written']:,} rows -> "
                      f"analysis.bike_od_leakage")

        t = Table(title="validation — analysis.bike_od_leakage")
        cols = ("month", "cells", "nta_pairs", "trips", "round_trip_pct",
                "residential_trips", "unknown_trips", "window_trips")
        for c in cols:
            t.add_column(c, justify="left" if c == "month" else "right")
        df = con.execute(cbod.OD_VALIDATION_SQL).fetchdf()
        bad = df[["bad_round", "bad_member"]].max().max()
        for r in df.tail(14).to_dict("records"):
            t.add_row(str(r["month"])[:7] if r["month"] is not None else "ALL",
                      f"{int(r['cells']):,}", f"{int(r['nta_pairs']):,}",
                      f"{int(r['trips']):,}", f"{r['round_trip_pct']:.2f}%",
                      f"{int(r['residential_trips'] or 0):,}",
                      f"{int(r['unknown_trips'] or 0):,}",
                      f"{int(r['window_trips'] or 0):,}")
        console.print(t)
        if bad:
            console.print("[red]round_trips or member_trips exceeds trips in at "
                          "least one month[/] — they are SUBSETS of trips, so that "
                          "is a double count, not a large number.")
            raise typer.Exit(1)
        console.print(
            "[dim]window_trips is the leakage window (evening OR weekend), "
            "counted ONCE. residential_trips is the only class the leakage view "
            "reads; an empty one means the classifier found no dock it could "
            "type, not a neighbourhood nobody leaves.[/]")
    finally:
        con.close()


@citibike_app.command("od-stats")
def citibike_od_stats(
    db: Path = typer.Option(None, "--db", help="Warehouse path."),
    origin: str = typer.Option(None, "--origin",
                               help="One origin NTA code, e.g. BK0101. Prints its "
                                    "top destinations in the leakage window."),
    window: str = typer.Option(None, "--window",
                               help="YYYY-MM,YYYY-MM. Default: the last 12 months "
                                    "present in the table."),
    top: int = typer.Option(12, "--top", help="Rows per listing."),
    conservation: bool = typer.Option(False, "--conservation",
                                      help="Reconcile OD trips against phase 1 "
                                           "`starts` per month/day_type/daypart."),
) -> None:
    """What the OD panel actually contains. READ-ONLY."""
    import datetime as _dt

    from loci.sources.cities.nyc import citibike_od as cbod

    con = _cb_connect(db, read_only=True)
    try:
        _od_require_table(con)
        tot = con.execute("""
            SELECT count(DISTINCT month), min(month), max(month),
                   count(DISTINCT origin_nta), count(DISTINCT destination_nta),
                   sum(trips), sum(round_trips)
            FROM analysis.bike_od_leakage""").fetchone()
        if not tot or tot[0] == 0:
            console.print("[red]analysis.bike_od_leakage is empty[/] — run "
                          "`loci citibike od-ingest`.")
            raise typer.Exit(1)
        months, first, last, o_ntas, d_ntas, trips, rt = tot
        span = (last.year - first.year) * 12 + (last.month - first.month) + 1
        console.print(
            f"[bold]{months}[/] months {first:%Y-%m}..{last:%Y-%m} "
            f"({'CONTIGUOUS' if months == span else f'[red]{span - months} MISSING[/]'}) · "
            f"[bold]{o_ntas}[/] origin NTAs -> {d_ntas} destination NTAs · "
            f"[bold]{trips:,}[/] trips ({rt / max(trips, 1):.2%} round)")

        if window:
            w0, w1 = (_dt.date(*_cb_month(x), 1) for x in window.split(","))
        else:
            w1 = last
            w0 = con.execute(
                "SELECT min(month) FROM (SELECT DISTINCT month FROM "
                "analysis.bike_od_leakage ORDER BY month DESC LIMIT 12)"
            ).fetchone()[0]
        console.print(f"[dim]window {w0:%Y-%m}..{w1:%Y-%m}[/]")

        t = Table(title="origin_type mix (trips, whole panel)")
        t.add_column("origin_type"); t.add_column("trips", justify="right")
        t.add_column("share", justify="right")
        for ot, n in con.execute(
                "SELECT origin_type, sum(trips) FROM analysis.bike_od_leakage "
                "GROUP BY 1 ORDER BY 2 DESC").fetchall():
            t.add_row(ot, f"{int(n):,}", f"{n / max(trips, 1):.1%}")
        console.print(t)
        console.print(
            "[dim]'unknown' is a real class, never a silent 'residential': a dock "
            "under the trip floor is one we cannot type. Only 'residential' "
            "origins enter analysis.bike_od_leakage_evening.[/]")

        if origin:
            rows = con.execute("""
                SELECT destination_nta, sum(trips) AS trips,
                       sum(trips) / nullif(sum(sum(trips)) OVER (), 0) AS share,
                       bool_or(out_of_nta) AS out_of_nta
                FROM analysis.bike_od_leakage_evening
                WHERE origin_nta = ? AND month BETWEEN ? AND ?
                GROUP BY 1 ORDER BY 2 DESC LIMIT ?
            """, [origin, w0, w1, top]).fetchall()
            if not rows:
                console.print(
                    f"[yellow]{origin}[/] has no residential-dock outbound flow in "
                    f"the window. That is NULL, never 0: either the operator has "
                    f"built no dock there that the classifier can type, or the "
                    f"docks are too quiet. It is a fact about a capital plan, not "
                    f"about the sidewalk.")
            else:
                t = Table(title=f"{origin} — evening/weekend destinations "
                                f"(round trips netted out)")
                t.add_column("destination"); t.add_column("trips", justify="right")
                t.add_column("share", justify="right"); t.add_column("out of NTA")
                for d, n, sh, out in rows:
                    t.add_row(d, f"{int(n):,}", f"{sh:.1%}",
                              "yes" if out else "[dim]own NTA[/]")
                console.print(t)
                console.print(
                    "[dim]Riders, not residents: Citi Bike mode share is low single "
                    "digits and skews young, male and higher-income. Docks are "
                    "endogenous to retail and density — a busy destination is "
                    "partly a place with many docks. CONTEXT ONLY (D76).[/]")

        if conservation:
            df = con.execute(cbod.OD_CONSERVATION_SQL).fetchdf()
            t = Table(title="conservation — OD trips vs phase 1 starts")
            for c in ("month", "day_type", "daypart", "od_trips", "p1_starts",
                      "excluded", "excluded_pct"):
                t.add_column(c, justify="left" if c in ("month", "day_type",
                                                        "daypart") else "right")
            for r in df.tail(top).to_dict("records"):
                t.add_row(str(r["month"])[:7], r["day_type"], r["daypart"],
                          f"{int(r['od_trips']):,}", f"{int(r['p1_starts']):,}",
                          f"{int(r['excluded']):,}", f"{r['excluded_pct']:.3f}%")
            console.print(t)
            worst = float(df["excluded_pct"].max())
            console.print(
                f"[dim]`excluded` is phase 1 starts minus OD trips and must be >= 0: "
                f"it is exactly the dockless ends and the ends on another operator's "
                f"dock, which OD drops and phase 1 keeps. Worst month/cell "
                f"{worst:.3f}%. A NEGATIVE value means OD invented trips.[/]")
            if float(df["excluded"].min()) < 0:
                console.print("[red]negative exclusion: OD has more trips than "
                              "phase 1 has starts.[/]")
                raise typer.Exit(1)
    finally:
        con.close()


@citibike_app.command("od-measures")
def citibike_od_measures(
    boroughs: str = typer.Option("MN,BK", help="Comma-separated borough codes, or ALL."),
    window_months: int = typer.Option(12, "--window-months",
                                      help="How many of the OD table's latest "
                                           "months to pool. 12 covers a full "
                                           "seasonal cycle; where people ride to "
                                           "in August is not where they ride to "
                                           "in February."),
    min_trips: int = typer.Option(200, "--min-trips",
                                  help="Below this many non-round evening/weekend "
                                       "trips out of an NTA's residential docks "
                                       "over the WHOLE window, write NULL rather "
                                       "than a destination read off a handful of "
                                       "rides."),
    re_sweep: bool = typer.Option(False, "--re-sweep",
                                  help="Rewrite even when every in-scope address "
                                       "already carries this window. Needed after "
                                       "`loci address-gaps` (which destroys the "
                                       "rows) only if the window has not moved — "
                                       "otherwise the rebuild is detected."),
    db: Path = typer.Option(None, "--db", help="Warehouse path (use a snapshot copy "
                                               "to prove a run without taking the "
                                               "live write lock)."),
    dry_run: bool = typer.Option(False, "--dry-run", help="Compute and print; write nothing."),
) -> None:
    """Where riders GO, on the card (Citi Bike phase 2, GTM-167).

        analysis.address.bike_od_top_nta / _top_nta_share / _out_share
        analysis.address.bike_od_window / bike_od_run_at
        analysis.address_category.bike_od_supplied_share

    Reads `analysis.bike_od_leakage` (run `loci citibike od-ingest` first),
    restricted to EVENING AND WEEKEND trips out of RESIDENTIAL-type docks —
    weekday pm_peak is deliberately excluded, because that is the commute home
    and not a choice about where to spend an evening.

    NEIGHBOURHOOD-WIDE, AND IT SAYS SO (owner ruling R3, 2026-09-15). There is no
    address-level OD: a dock serves a few hundred addresses. Every value here is
    the NTA's value stamped identically on every address in it, and every
    renderer must carry the "neighbourhood-wide" caveat — `model/bike_od.py`'s
    `card_line()` is the sanctioned wording.

    RIDERS, NEVER RESIDENTS. Citi Bike mode share is low single digits and skews
    young, male and higher-income. This is where CYCLISTS go.

    NULL, NEVER ZERO. An NTA with no residential dock, or under --min-trips in
    the window, gets NULL while still carrying the window and run_at, so
    "measured, no dock" is distinguishable from "never run".

    CONTEXT ONLY (D76). Nothing here enters gap_score, supply_ratio_vs_base, a
    recommendation grade, or the revenue model's λ (owner ruling R1: revenue.py
    is untouched). It has to clear `loci citibike od-validate` before it is a
    number on a card at all rather than a sentence of prose.
    """
    from loci.model import bike_od as bod

    boros = _parse_boroughs(boroughs)
    con = _cb_connect(db, read_only=dry_run)
    if not dry_run:
        locidb.init_schema(con)
    try:
        _od_require_table(con)
        nta, cat, report = bod.build_bike_od(
            con, boros, window_months=window_months, min_trips=min_trips,
            re_sweep=re_sweep, dry_run=dry_run)

        console.print(
            f"window [bold]{report['window']}[/] · {report['origin_ntas']:,} origin "
            f"NTAs above the {report['min_origin_trips']:,}-trip floor · "
            f"{report['destination_pairs']:,} NTA pairs · "
            f"{report['universe_ntas']:,} NTAs in the measurable supply universe")
        s = report["supplied"]
        console.print(
            f"median out-of-NTA share [bold]{report['median_out_share']:.1%}[/] · "
            f"{100 * s['outbound_outside_universe_share']:.1f}% of outbound trips "
            f"land outside the measurable universe (fewer than "
            f"{report['universe_min_addresses']:,} lot addresses there, so supply "
            f"density is an artefact) · {s['origins_dropped_outside_universe']} "
            f"origin NTA(s) dropped for sending more than "
            f"{100 * bod.MAX_OUTSIDE_UNIVERSE_SHARE:.0f}% of their riders there, "
            f"{s['origins_dropped_thin_outbound']} more for fewer than "
            f"{s['min_outbound_trips']:,} measurable outbound trips")
        iqr = report["top_share_monthly_iqr"]
        if iqr.get("months"):
            console.print(
                f"[dim]the window pools {iqr['months']} months and is "
                f"summer-weighted (August ~2.5x February): the top-share moves by "
                f"{iqr['median_iqr']:.1%} IQR at the median NTA, "
                f"{iqr['p90_iqr']:.1%} at the 90th. Reported, never stored — it is "
                f"a property of the window, not of the address.[/]")

        t = Table(title=f"OD leakage — {','.join(boros)} @ {report['window']} "
                        f"(NTAs with a residential dock only)")
        for c, j in (("measure", "left"), ("n", "right"), ("p50", "right"),
                     ("p90", "right"), ("max", "right")):
            t.add_column(c, justify=j)
        for col, frame in (("bike_od_top_nta_share", nta),
                           ("bike_od_out_share", nta),
                           ("bike_od_supplied_share", cat)):
            v = frame[col].dropna()
            if not len(v):
                t.add_row(col, "0", "-", "-", "-")
                continue
            t.add_row(col, f"{len(v):,}", f"{v.median():.3f}",
                      f"{v.quantile(0.9):.3f}", f"{v.max():.3f}")
        console.print(t)

        top = nta.sort_values("bike_od_out_share", ascending=False).head(10)
        leak = Table(title="leakiest neighbourhoods — most riders leaving in the "
                           "evening and at weekends")
        for c, j in (("origin NTA", "left"), ("top destination", "left"),
                     ("top share", "right"), ("out share", "right"),
                     ("trips", "right")):
            leak.add_column(c, justify=j)
        for r in top.to_dict("records"):
            leak.add_row(r["nta_code"], r["bike_od_top_nta"],
                         f"{r['bike_od_top_nta_share']:.1%}",
                         f"{r['bike_od_out_share']:.1%}",
                         f"{r['trips_total']:,.0f}")
        console.print(leak)

        if dry_run:
            console.print("[dim]--dry-run:[/] nothing written.")
            raise typer.Exit(0)
        w = report["_written"]
        if "skipped" in w:
            console.print(f"[dim]no write:[/] {w['skipped']}")
            raise typer.Exit(0)
        console.print(
            f"[green]ok[/] {w['addresses_stamped']:,} addresses stamped · "
            f"{w['addresses_with_a_destination']:,} carry a destination · "
            f"{w['addresses_null_no_residential_dock']:,} are NULL (no residential "
            f"dock, or under the trip floor — never 0) · "
            f"{w['address_category_rows']:,} address_category rows filled "
            f"(ratio > 1 only, D39)")

        v = Table(title="validation — analysis.address")
        cols = ("borough", "addresses", "stamped", "with_a_reading",
                "impossible_zero", "p50_out_share", "min_out_share",
                "max_out_share", "max_top_share", "distinct_values_per_nta")
        for c in cols:
            v.add_column(c, justify="left" if c == "borough" else "right")
        for r in con.execute(bod.VALIDATION_SQL).fetchdf().to_dict("records"):
            v.add_row(str(r["borough"] or "ALL"),
                      *[("-" if r[c] is None else f"{r[c]:,}") for c in cols[1:]])
        console.print(v)
        console.print(
            "[dim]impossible_zero must be 0 (no reading is NULL, never 0) and "
            "distinct_values_per_nta must be 1 — the value is neighbourhood-wide "
            "by construction (R3), so two addresses in one NTA disagreeing means "
            "the join found a second nta_code.[/]")
    finally:
        con.close()


@citibike_app.command("od-validate")
def citibike_od_validate(
    window_months: int = typer.Option(12, "--window-months"),
    placebo_only: bool = typer.Option(False, "--placebo-only",
                                      help="Run the pre-condition and stop. The "
                                           "DOT half needs "
                                           "staging.dot_pedestrian_count."),
    csv: Path = typer.Option(None, "--csv",
                             help="Write the 15x15 placebo matrix here."),
    db: Path = typer.Option(None, "--db", help="Warehouse path."),
) -> None:
    """Does the OD measure survive? The two tests from GTM-167 §Validation.

    PRE-CONDITION — the category placebo. `bike_od_supplied_share` for grocery is
    supposed to be about where groceries are. If the vector computed with the
    grocery threshold ranks neighbourhoods the same way as the one computed with
    the bar threshold, it is destination retail density in a costume and every
    category is the same column fifteen times. Bar: the mean off-diagonal rank
    correlation must stay BELOW the diagonal's 1.0 (under 0.95). Fail and the
    finding ships as PROSE ONLY — no column, no card number.

    GRADUATION — DOT convergent validity. Rank-correlate destination-NTA
    evening/weekend inflow against DOT PM pedestrian counts aggregated to NTA.
    Bar: ρ ≥ +0.5 AND the placebo must pass. Reported beside the BASELINE TO
    BEAT — destination-NTA open POIs per address against the same counts. If the
    baseline does as well, the trip table added nothing a POI count did not
    already say.

    DOT publishes am / md / pm and no evening period, so PM is the closest
    published thing to the leakage window, and it is a known mismatch: DOT's PM
    includes the commute home, which the leakage window deliberately excludes.

    READ-ONLY. Writes nothing, takes no write lock; safe to run against the live
    warehouse while a build holds it.
    """
    from loci.model import bike_od as bod

    con = _cb_connect(db, read_only=True)
    try:
        _od_require_table(con)
        window = bod.window_bounds(con, window_months)
        mat, pl = bod.placebo(con, window)
        if csv:
            csv.parent.mkdir(parents=True, exist_ok=True)
            mat.to_csv(csv)
            console.print(f"[dim]placebo matrix -> {csv}[/]")

        t = Table(title=f"category placebo — {bod.window_label(*window)} "
                        f"({pl['n_origin_ntas']} origin NTAs)")
        t.add_column("category", justify="left")
        for c in mat.columns:
            t.add_column(c[:6], justify="right")
        for c in mat.index:
            t.add_row(c, *[("-" if r != r else f"{r:.2f}") for r in mat.loc[c]])
        console.print(t)
        verdict = "[green]PASSES[/]" if pl["passes"] else "[red]FAILS[/]"
        console.print(
            f"[dim]description only:[/] mean off-diagonal rho "
            f"{pl['mean_offdiag']:.3f} (median {pl['median_offdiag']:.3f}, max "
            f"{pl['max_offdiag']:.3f}). This is NOT the gate — destination supply "
            f"density already correlates across categories at ~0.76, so any "
            f"off-diagonal bar passes everything.")
        n = Table(title=f"the gate: each category vs the null baseline "
                        f"({pl['null_baseline']:.1%} of measurable outbound trips "
                        f"land in one of the {pl['null_baseline_all_category_ntas']} "
                        f"destinations above median in ALL 15 categories)")
        for c, j in (("category", "left"), ("origins", "right"),
                     ("median share", "right"), ("median null", "right"),
                     ("excess", "right"), ("beats null", "right"),
                     ("verdict", "left")):
            n.add_column(c, justify=j)
        for r in pl["per_category"].to_dict("records"):
            n.add_row(r["category"], f"{r['n_origins']:,}",
                      f"{r['median_share']:.3f}", f"{r['median_null']:.3f}",
                      f"{r['median_excess']:+.3f}",
                      f"{r['share_of_origins_beating_null']:.0%}",
                      "[green]ships[/]" if r["passes"] else "[red]prose only[/]")
        n.caption = (f"a category earns its column only by beating the null by "
                     f"{pl['bar']:.2f} at the median origin.")
        console.print(n)
        console.print(f"overall placebo — {verdict}")
        if not pl["passes"]:
            console.print(
                f"[red]{len(pl['categories_failing'])} categories do not beat the "
                f"null[/] ({', '.join(pl['categories_failing'])}): for those, "
                f"'riders already reach this elsewhere' is indistinguishable from "
                f"'riders go to the busy neighbourhoods'. Ship them as PROSE; do "
                f"not ship bike_od_supplied_share as a column for them.")
        if placebo_only:
            raise typer.Exit(0 if pl["passes"] else 1)

        d = bod.dot_validation(con, window)
        g = Table(title="DOT convergent validity — destination-NTA inflow vs "
                        f"DOT {d['dot_period'].upper()} pedestrian counts")
        for c, j in (("test", "left"), ("value", "right"), ("bar", "right")):
            g.add_column(c, justify=j)
        g.add_row("ρ  inflow vs DOT", f"{d['rho_inflow_vs_dot']:+.3f}",
                  f"≥ {d['bar']:+.2f}")
        g.add_row("ρ  baseline (POIs per 1,000 residential units) vs DOT",
                  f"{d['rho_baseline_supply_density_vs_dot']:+.3f}", "to beat")
        g.add_row("placebo — categories failing the null baseline",
                  f"{len(d['placebo_categories_failing'])}", "0")
        g.caption = (f"{d['n_ntas']} NTAs carry both, over {d['dot_points']:,} DOT "
                     f"count points (bridge midpoints excluded).")
        console.print(g)
        console.print(
            f"beats the baseline: {'[green]yes[/]' if d['beats_baseline'] else '[red]no[/]'}   "
            f"overall: {'[green]GRADUATES[/]' if d['passes'] else '[red]CONTEXT ONLY[/]'}")
        if not d["passes"]:
            console.print(
                "[dim]Staying CONTEXT ONLY is the D76 default, not a failure of "
                "the build: the measure remains on the card with its caveats and "
                "enters no score, no ratio and no grade.[/]")
        raise typer.Exit(0 if d["passes"] else 1)
    finally:
        con.close()
