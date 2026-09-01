"""Loci command line.

    loci init-db
    loci check-sources [--urls]
    loci check-questions
    loci ingest --source overture_places --city nyc [--dry-run]
    loci grid   --city nyc --resolution 9
    loci score  --threshold 10
    loci model  --t0 2013 --t1 2023
    loci export --format pmtiles

No analysis logic lives here; commands are thin wrappers over the packages.
"""
from __future__ import annotations

from pathlib import Path

import typer
from rich.console import Console
from rich.table import Table

from loci import db as locidb
from loci import questions, registry, tickets as tickets_mod
from loci import sources as source_adapters

app = typer.Typer(add_completion=False, help=__doc__)
console = Console()

REPO_ROOT = Path(__file__).resolve().parents[2]


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
def score(threshold: int = typer.Option(10, help="Walk minutes: 5, 10 or 15.")) -> None:
    """Multi-source Dijkstra access scoring, then the DNCI."""
    if threshold not in (5, 10, 15):
        raise typer.BadParameter("threshold must be 5, 10 or 15")
    raise NotImplementedError("W2 — see docs/TICKETS.md, epic E2.")


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
