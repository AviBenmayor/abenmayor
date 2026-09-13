.PHONY: help setup db-init check tickets nyc chains-refresh clean

help:          ## Show targets
	@grep -E '^[a-z-]+:.*?##' $(MAKEFILE_LIST) | sed 's/:.*##/\t/' | column -t -s "$$(printf '\t')"

setup:         ## Install deps and create .env
	uv sync
	@test -f .env || (cp .env.example .env && echo "created .env — add CENSUS_API_KEY")

db-init:       ## Create data/loci.duckdb and apply the schema
	uv run loci init-db

check:         ## Registry + URL sweep + QUESTIONS drift + decisions + load-bearing unit tests
	uv run loci check-sources --urls
	uv run loci check-questions
	uv run loci check-tickets
	uv run pytest tests/test_chains_normalize.py tests/test_chains_detect.py \
	              tests/test_chains_watchlist.py -q

tickets:       ## Regenerate docs/TICKETS.md + docs/linear-*.{csv,json}
	uv run loci gen-tickets

nyc: db-init   ## Full NYC pipeline
	uv run loci ingest --source overture_places --city nyc
	uv run loci grid   --city nyc --resolution 9
	uv run loci dedup
	uv run loci score
	uv run loci gaps
	uv run loci model  --t0 2013 --t1 2023
	uv run loci export --format pmtiles

chains-refresh: ## Monthly: detect chains, enrich from press, regenerate docs/CHAINS.md
	uv run loci chains refresh

clean:         ## Drop intermediates and the database (keeps data/raw)
	rm -rf data/interim/* data/processed/* data/loci.duckdb
