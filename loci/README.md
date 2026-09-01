# Loci

Walkable daily-needs retail completeness and **residual undersupply**, at H3 hex resolution.
New York City first; the scoring engine is city-agnostic.

> Conditional on population density, household income, transit access, and commercial
> zoning capacity, some NYC hexes have materially less daily-needs retail than otherwise
> comparable hexes. That residual gap — not the raw count — is the opportunity signal,
> and it should predict subsequent residential growth.

| Read this | For |
|---|---|
| **[docs/CONTEXT.md](docs/CONTEXT.md)** | The charter — thesis, sources, method, threats. Authoritative. Read before writing code. |
| **[docs/CHECKPOINT.md](docs/CHECKPOINT.md)** | Where we are — state, blockers, decision log. Read first when resuming. |
| **[docs/QUESTIONS.md](docs/QUESTIONS.md)** | The build compass — research questions tiered by rigor, each mapped to the tickets that answer it, plus the homework list. `make check` keeps it in step with the tickets. |
| **[docs/TICKETS.md](docs/TICKETS.md)** | Work breakdown, 6 milestones / 61 issues. Generated — never hand-edit. |

## Quick start

```bash
make setup      # uv sync + create .env  (add CENSUS_API_KEY)
make db-init    # create data/loci.duckdb and apply the schema
make check      # registry consistency + URL sweep
uv run loci sources
```

No Docker, no daemon, no server — DuckDB is embedded.

## Layout

```
docs/     what humans read   — CONTEXT · CHECKPOINT · QUESTIONS · TICKETS · Linear exports
src/loci/ the code             — package, plus registry.yaml and sql/
data/     what machines make   — raw/ interim/ processed/ + loci.duckdb  (gitignored)
```

| Path | Contract |
|---|---|
| `src/loci/registry.yaml` | Machine-readable mirror of CONTEXT.md §3. `make check` enforces agreement. |
| `src/loci/sql/002_schema.sql` | `raw` → `staging` → `analysis`. `staging.poi` is the normalized contract. |
| `src/loci/sources/universal/` | Nationally available. Must work for any US city. |
| `src/loci/sources/cities/nyc/` | NYC-only, best-quality. Never referenced downstream of staging. |
| `src/loci/score/` | **City-agnostic.** No NYC column names — this is the portability guarantee. |
| `src/loci/model/` | Supply model, residual, panel test. |

## Three decisions worth knowing before reading the code

**Access uses one multi-source Dijkstra per category, not one isochrone per hex.**
15 graph traversals instead of ~7,400. Minutes, not hours. (§4.3)

**The index is a weighted geometric mean, not arithmetic.** A hex with fifty restaurants
and no grocery, pharmacy or laundromat must not score well — that is exactly the failure
the project exists to detect, and only the geometric form punishes zeros. (§4.4)

**DuckDB `GEOMETRY` carries no SRID.** Everything stored is EPSG:4326 by convention;
metric work reprojects explicitly. The database will not catch a violation of this.

## Cost

$0–100 projected against a $500 ceiling. Everything is open data except a Google Places
ground-truth sample used to test whether the measured retail gap is real or an artifact of
POI coverage bias — the threat that could invalidate the entire finding (§7.1).

## Status

Charter, scaffold and database complete. No analysis logic yet — see
[docs/CHECKPOINT.md](docs/CHECKPOINT.md).
