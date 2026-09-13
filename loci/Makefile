.PHONY: help setup db-init check tickets paid-sources nyc chains-refresh clean

help:          ## Show targets
	@grep -E '^[a-z-]+:.*?##' $(MAKEFILE_LIST) | sed 's/:.*##/\t/' | column -t -s "$$(printf '\t')"

setup:         ## Install deps and create .env
	uv sync
	@test -f .env || (cp .env.example .env && echo "created .env — add CENSUS_API_KEY")

db-init:       ## Create data/loci.duckdb and apply the schema
	uv run loci init-db

check:         ## Registry + URL sweep + QUESTIONS drift + decisions + ledger coverage + load-bearing unit tests
	uv run loci check-sources --urls
	uv run loci check-questions
	uv run loci check-tickets
	uv run loci check-presence
	uv run pytest tests/test_chains_normalize.py tests/test_chains_detect.py \
	              tests/test_chains_watchlist.py tests/test_poi_presence.py \
	              tests/test_webmap_character.py tests/test_sidewalk_count.py \
	              tests/test_street_frame.py tests/test_paid_sources.py -q

tickets:       ## Regenerate docs/TICKETS.md + docs/linear-*.{csv,json}
	uv run loci gen-tickets

paid-sources:  ## Regenerate docs/PAID-SOURCES.md from the registry wishlist
	# GENERATED, like TICKETS.md: `loci check-sources` (and so `make check`)
	# fails if docs/PAID-SOURCES.md is not a byte-identical render, so edit
	# the `status: wishlist` entries in src/loci/registry.yaml, never the doc.
	uv run loci gen-paid-sources

nyc: db-init   ## Full NYC pipeline
	uv run loci ingest --source overture_places --city nyc
	uv run loci grid   --city nyc --resolution 9
	uv run loci dedup
	uv run loci poi-snapshot
	uv run loci score
	uv run loci gaps
	uv run loci model  --t0 2013 --t1 2023
	uv run loci export --format pmtiles

chains-refresh: ## Monthly: filing pipeline, first-seen ledger, detect chains, enrich from press, regenerate docs/CHAINS.md
	# The filing pipeline goes FIRST, before detect, for two reasons: `loci
	# chains render` reads analysis.storefront_pipeline for the "Pipeline (gov
	# filings)" column (it degrades to dashes without it, rather than failing),
	# and the roll-up is what the 'gov_filing' first-seen kind is computed from.
	# Order against poi-snapshot does not matter -- this step reads only
	# staging.storefront_filing.
	uv run loci storefront-pipeline build
	# `loci chains refresh` runs `loci poi-snapshot` as step 1/4, BEFORE detect:
	# detect reads analysis.poi_first_seen and raises without it, and a month's
	# observation cannot be recovered once the month has passed. Keeping it
	# inside the subcommand rather than as a second line here is what makes the
	# cron and the human run the identical sequence.
	uv run loci chains refresh

clean:         ## Drop intermediates and the database (keeps data/raw)
	rm -rf data/interim/* data/processed/* data/loci.duckdb
