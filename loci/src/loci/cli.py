"""Loci command line.

    loci init-db
    loci check-sources [--urls]
    loci check-questions
    loci gaps [--expected 0.8]
    loci gaps-sweep [--expected 0.75,0.80,0.85,0.90]   (read-only)
    loci spacing                                        (read-only)
    loci ingest --source overture_places --city nyc [--dry-run]
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
         expected: float = typer.Option(0.80, help="Prevalence a category needs before its absence is a gap.")) -> None:
    """Present-day gap screen: walkable hexes missing an expected business."""
    from loci.model.gaps import build_gaps
    con = locidb.connect(); locidb.init_schema(con)
    n, _ = build_gaps(con, threshold=threshold, min_present=min_present, expected=expected)
    console.print(f"[green]ok[/] {n} gap hexes (missing an expected business) at expected={expected}")


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
        results[e] = (len(rows), Counter(r[4] for r in rows), Counter(c for r in rows for c in r[6].split(",")))
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
