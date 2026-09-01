# Execution protocol — for autonomous ticket executors

You are executing **one Linear ticket** in the Loci repo. Read this in full, then do
exactly that ticket. Do not expand scope.

## Orient (read these first)
- `docs/CONTEXT.md` — the charter. The thesis is a **residual, not a raw count**. Obey the
  threats to validity; they are the point of the project.
- `src/loci/sql/002_schema.sql` — the DuckDB schema. `staging.poi` is the normalized
  contract every source lands in.
- `src/loci/sources/cities/nyc/dohmh.py` — the **reference adapter**. Clone its shape.

## Hard rules (violating these fails the ticket)
1. **staging.poi is the only contract.** Adapters normalize into it. Nothing in
   `src/loci/score/` or `src/loci/model/` may reference a raw source column or an NYC-only
   name. City adapters live in `src/loci/sources/cities/<city>/`; universal sources in
   `src/loci/sources/universal/`.
2. **Category vocabulary is fixed** — the 15 slugs in `src/loci/categories.py`. Map onto
   them; never invent a category.
3. **DuckDB GEOMETRY has no SRID.** Everything is EPSG:4326 by convention. Reproject
   explicitly for metric work. Access connections via `loci.db.connect()`.
4. **Adapters self-register** by subclassing `SourceAdapter` and setting `source_id` to
   match `registry.yaml`. Add your adapter as ONE new file. Do **not** edit
   `sources/__init__.py`, `cli.py`, `CONTEXT.md`, `CHECKPOINT.md`, or the ticket files —
   the orchestrator owns those. If you think a shared file must change, say so in your
   report instead of editing it.
5. **`load()` is inherited** from `SourceAdapter` and is idempotent. You implement only
   `fetch()` and `normalize()`. Do not reimplement `load()`.

## Definition of done
- Your source ingests: `uv run loci ingest --source <id> --limit 2000` writes rows to
  `staging.poi`, all geometries inside the NYC bbox (lon −74.3…−73.6, lat 40.4…41.0).
- A unit test for `normalize()` (dedup + bad-geometry drop + category mapping), passing
  under `uv run pytest`.
- `uv run loci check-sources` still passes.
- Report back: rows normalized, category breakdown, any scope decision you made and why,
  and any shared-file change you need the orchestrator to make.

## What NOT to do
- No new dependencies without saying so.
- No analysis logic in an ingest ticket.
- Never claim done without running the ingest and the test yourself.
