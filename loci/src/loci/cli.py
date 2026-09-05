"""Loci command line.

    loci init-db
    loci check-sources [--urls]
    loci check-questions
    loci gaps [--expected 0.8] [--rule window|reach]
    loci gaps-sweep [--expected 0.75,0.80,0.85,0.90]   (read-only)
    loci reach-table [--quantile 0.80] [--write]        (read-only unless --write)
    loci spacing                                        (read-only)
    loci conveniences [--borough MN] [--limit 0] [--dry-run]
    loci address-gaps [--borough ALL] [--reach tiers|p80] [--limit 0] [--dry-run]
    loci ingest --source overture_places --city nyc [--dry-run]
    loci ingest-zbp [--year 2023] [--dry-run]           (validation only)
    loci zbp-compare [--year]                            (read-only)
    loci grid   --city nyc --resolution 9
    loci score  [--limit-min 30]
    loci model  --t0 2013 --t1 2023
    loci export --format pmtiles

No analysis logic lives here; commands are thin wrappers over the packages.
"""
from __future__ import annotations

from pathlib import Path

import typer
from dotenv import load_dotenv
from rich.console import Console
from rich.table import Table

from loci import db as locidb
from loci import questions, registry, tickets as tickets_mod
from loci import sources as source_adapters

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
def controls(source: str = typer.Option("pluto", help="Control source: pluto.")) -> None:
    """Build analysis.hex_controls from a control source."""
    con = locidb.connect()
    locidb.init_schema(con)
    if source == "pluto":
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


@app.command(name="zbp-compare")
def zbp_compare(
    year: int = typer.Option(None, help="Vintage to compare against; defaults to the latest ingested."),
) -> None:
    """Compare Loci's deduped POI counts to ZBP establishment counts, per
    category and NYC ZIP (VALIDATION ONLY -- see registry.yaml `census_zbp`)."""
    from loci.model.zbp_compare import run_comparison

    con = locidb.connect()
    locidb.init_schema(con)
    run_comparison(con, year=year, console=console)


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


@app.command()
def score(limit_min: int = typer.Option(30, help="Persist hex↔business network distances up to this many walk-minutes.")) -> None:
    """Walk-network access: persist hex_poi_distance, derive hex_access, then the DNCI."""
    from loci.score.access import build_access
    from loci.score.dnci import build_dnci
    con = locidb.connect(); locidb.init_schema(con)
    n_acc = build_access(con, limit=limit_min * 80.0)
    n_pairs = con.execute("SELECT count(*) FROM analysis.hex_poi_distance").fetchone()[0]
    n_dnci = build_dnci(con)
    console.print(f"[green]ok[/] {n_pairs:,} hex↔business pairs within {limit_min} min; "
                  f"{n_acc:,} hex_access rows; {n_dnci:,} DNCI rows")


@app.command()
def gaps(threshold: int = typer.Option(10), min_present: int = typer.Option(12),
         expected: float = typer.Option(0.80, help="Prevalence a category needs before its absence is a gap. Ignored by --rule reach."),
         rule: str = typer.Option("window", help="'window' (default, writes analysis.hex_gaps, unchanged) or "
                                   "'reach' (QUESTIONS D6/CHECKPOINT D33: fixed per-category reach, writes "
                                   "analysis.hex_gaps_reach — monotone, does not touch hex_gaps).")) -> None:
    """Present-day gap screen: walkable hexes missing an expected business."""
    from loci.model.gaps import build_gaps
    con = locidb.connect(); locidb.init_schema(con)
    n, _ = build_gaps(con, threshold=threshold, min_present=min_present, expected=expected, rule=rule)
    where = "analysis.hex_gaps" if rule == "window" else "analysis.hex_gaps_reach"
    console.print(f"[green]ok[/] {n} gap hexes -> {where} (rule={rule})")


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
    limit: int = typer.Option(0, help="Cap addresses fetched, for smoke runs (0 = all)."),
    dry_run: bool = typer.Option(False, "--dry-run", help="Compute and print the summary; write nothing."),
) -> None:
    """Address-level convenience check: which of the 15 categories sit within the
    owner-set walk norm (src/loci/conveniences.yaml) of each residential address in
    `borough`. Writes analysis.address_convenience unless --dry-run."""
    from loci.model import conveniences as conv
    from loci.sources.cities.nyc.addresses import load_residential_addresses

    b = borough.upper()
    con = locidb.connect(read_only=dry_run)
    if not dry_run:
        locidb.init_schema(con)

    addresses_df = load_residential_addresses(con, borough=b)
    if limit:
        addresses_df = addresses_df.head(limit).reset_index(drop=True)
    if addresses_df.empty:
        console.print(f"[yellow]no residential addresses for borough={b}[/]")
        raise typer.Exit(0)

    if dry_run:
        console.print(f"[dim]--dry-run:[/] {len(addresses_df)} addresses (borough={b}), "
                      f"loading walk graph + computing (no write)…")
        summary = conv.convenience_summary(con, addresses_df)
    else:
        n = conv.build_address_convenience(con, addresses_df, borough=b)
        cat_unsat = dict(conv.category_unsatisfied_shares(con, b))
        dist = conv.n_unsatisfied_distribution(con, b)
        fully_units = next((share_units for n_un, _share_addr, share_units in dist if n_un == 0), 0.0)
        summary = {
            "n_addresses": n,
            "n_units": float(addresses_df["units"].sum()),
            "category_satisfied_share": {c: 1.0 - s for c, s in cat_unsat.items()},
            "share_fully_satisfied": fully_units,
        }
        console.print(f"[green]ok[/] wrote {n} rows to analysis.address_convenience (borough={b})")

    console.print(f"{summary['n_addresses']} addresses, {summary['n_units']:.0f} units, borough={b}")
    for cat, share in summary["category_satisfied_share"].items():
        console.print(f"  {cat:14} satisfied {100*share:.1f}%")
    console.print(f"[bold]{100*summary['share_fully_satisfied']:.1f}%[/] of addresses "
                  f"(unit-weighted) have all 15 categories satisfied")


@app.command(name="address-gaps")
def address_gaps_cmd(
    borough: str = typer.Option("ALL", help="ALL|MN|BX|BK|QN|SI"),
    reach: str = typer.Option("tiers", help="'tiers' (CHECKPOINT D41, default) or 'p80' (reach.yaml)."),
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
        df = ag.compute_address_gaps(con, addresses_df, reach_source=reach)
        console.print("[dim]--dry-run: computed, nothing written.[/]")
    else:
        n, df = ag.build_address_gaps(con, addresses_df, reach_source=reach)
        console.print(f"[green]ok[/] wrote {n:,} rows -> analysis.address_gaps (borough={b}, reach={reach})")

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


@app.command(name="gaps-sweep")
def gaps_sweep(expected: str = typer.Option("0.75,0.80,0.85,0.90", help="Comma-separated prevalence thresholds."),
               threshold: int = typer.Option(10), min_present: int = typer.Option(12)) -> None:
    """Compare the gap screen across prevalence thresholds. Read-only: writes nothing."""
    from collections import Counter
    from loci.categories import CATEGORIES
    from loci.model.gaps import compute_gaps
    con = locidb.connect(read_only=True)
    vals = [float(v) for v in expected.split(",")]
    results = {}
    prevalence = None
    for e in vals:
        rows, prevalence = compute_gaps(con, threshold=threshold, min_present=min_present, expected=e)
        results[e] = (len(rows), Counter(r[4] for r in rows), Counter(c for r in rows for c in r[-1].split(",")))
    cats = sorted(CATEGORIES, key=lambda c: -prevalence[c])
    table = Table(title=f"gap screen by `expected`  ({threshold} min, ≥{min_present}/15 present)  cells = lead / any")
    table.add_column("category"); table.add_column("prev.", justify="right")
    for e in vals:
        table.add_column(f"{e:.2f}", justify="right")
    for c in cats:
        cells = [c, f"{prevalence[c]:.2f}"]
        for e in vals:
            _, lead, anym = results[e]
            cells.append(f"{lead.get(c, 0)} / {anym.get(c, 0)}" if prevalence[c] >= e else "·")
        table.add_row(*cells)
    table.add_row("[bold]gap hexes[/]", "", *[f"[bold]{results[e][0]}[/]" for e in vals])
    console.print(table)
    console.print("[dim]lead = most-expected missing category per hex · any = hexes missing it at all · "
                  "'·' = below the threshold, so its absence never counts.[/]")


@app.command()
def validate(
    per_decile: int = typer.Option(20, help="Hexes sampled per income decile (10 deciles)."),
    categories: str = typer.Option("all", help="Comma-separated Loci categories, or 'all'."),
    dry_run: bool = typer.Option(True, "--dry-run/--run", help="Plan only (default) or spend calls."),
    recount_local: bool = typer.Option(False, "--recount-local",
        help="Recompute n_overture/n_osm/n_city_source/n_local_canonical for every EXISTING row "
             "in analysis.coverage_validation against current staging.poi/poi_dedup. Spends no "
             "Google calls and touches n_ground_truth for nobody; ignores --dry-run/--run/sampling."),
) -> None:
    """Coverage validation (P3): Google Places as SAMPLED ground truth, counts only, hard budget."""
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
    s = smp.draw_sample(con, per_decile=per_decile)
    p = smp.plan(s, cats)
    client = GooglePlacesClient()
    console.print(f"sample: {p['hexes']} hexes × {p['categories']} categories = {p['calls']} calls; "
                  f"est. ${p['est_cost_usd']} beyond the free tier. Budget {client.calls_used}/{client.budget} used.")
    if dry_run:
        console.print("[dim]--dry-run: nothing spent, nothing written. Re-run with --run.[/]")
        raise typer.Exit(0)
    if p["calls"] > client.calls_left:
        console.print(f"[red]refusing:[/] {p['calls']} calls needed, {client.calls_left} left in budget.")
        raise typer.Exit(1)
    n = smp.run(con, client, s, cats, dry_run=False)
    console.print(f"[green]ok[/] {n} rows in analysis.coverage_validation; budget now {client.calls_used}/{client.budget}")


@app.command()
def spacing(threshold: int = typer.Option(10), citywide: bool = typer.Option(False, "--citywide", help="Include the NJ/Westchester fringe."),
            per_category: int = typer.Option(2000, help="Businesses sampled per category for the spacing table.")) -> None:
    """Read-only, on the WALK NETWORK: how far apart same-type businesses sit, and how far each gap hex is from its missing business."""
    from loci.model.spacing import same_type_spacing, gap_to_nearest, _graph, WALK_M_PER_MIN
    con = locidb.connect(read_only=True)
    console.print("[dim]loading walk graph…[/]")
    graph = _graph()
    t1 = Table(title="Same-type spacing — network metres to the nearest OTHER business of the same category")
    for col in ("category", "n", "sampled", "p10", "median", "p90", "> 10 min", "> 30 min"):
        t1.add_column(col, justify="right" if col != "category" else "left")
    for cat, n, ns, p10, med, p90, far, cens in same_type_spacing(con, core_only=not citywide, per_category=per_category, graph=graph):
        t1.add_row(cat, str(n), str(ns), f"{p10:.0f}", f"{med:.0f}", f"{p90:.0f}" if cens < .10 else f">{p90:.0f}", f"{100*far:.1f}%", f"{100*cens:.1f}%")
    console.print(t1)
    t2 = Table(title=f"Gap hexes ({threshold} min) — network metres from the hex to the nearest business of its lead missing category (from hex_poi_distance)")
    for col in ("lead missing", "gaps", "min", "median", "p90", "> 1.5 km", "> 30 min"):
        t2.add_column(col, justify="right" if col != "lead missing" else "left")
    for cat, n, mn, med, p90, far, cens in gap_to_nearest(con, threshold=threshold, core_only=not citywide, graph=graph):
        t2.add_row(cat, str(n), f"{mn:.0f}", f"{med:.0f}", f"{p90:.0f}", str(far), str(cens))
    console.print(t2)
    console.print(f"[dim]Walking at {WALK_M_PER_MIN:.0f} m/min: 800 m = 10 min, 1,200 m = 15 min, 2,400 m = 30 min. "
                  "Same graph, snapping and component pruning as hex_access.[/]")


@app.command()
def model(t0: int = 2013, t1: int = 2023) -> None:
    """Fit the supply model, extract residuals, run the growth test."""
    raise NotImplementedError("W3 — see docs/TICKETS.md, epic E3.")


@app.command()
def export(fmt: str = typer.Option("pmtiles", "--format")) -> None:
    """Export tiles and charts for the public artifact."""
    raise NotImplementedError("W4 — see docs/TICKETS.md, epic E4.")


if __name__ == "__main__":
    app()
