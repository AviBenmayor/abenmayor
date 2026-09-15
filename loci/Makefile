.PHONY: help setup db-init check tickets paid-sources portability nyc chains-refresh clean

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
	              tests/test_street_frame.py tests/test_paid_sources.py \
	              tests/test_dot_export.py tests/test_recommendation.py \
	              tests/test_portability.py tests/test_forecast.py \
	              tests/test_webmap_forecast.py tests/test_recommend.py \
	              tests/test_google_types_drift.py -q

tickets:       ## Regenerate docs/TICKETS.md + docs/linear-*.{csv,json}
	uv run loci gen-tickets

paid-sources:  ## Regenerate docs/PAID-SOURCES.md from the registry wishlist
	# GENERATED, like TICKETS.md: `loci check-sources` (and so `make check`)
	# fails if docs/PAID-SOURCES.md is not a byte-identical render, so edit
	# the `status: wishlist` entries in src/loci/registry.yaml, never the doc.
	uv run loci gen-paid-sources

portability:   ## Regenerate docs/PORTABILITY.md from the registry `portability` blocks
	# GENERATED, like PAID-SOURCES.md: `loci check-sources` (and so `make
	# check`) fails if docs/PORTABILITY.md is not a byte-identical render.
	# Edit the `portability:` blocks in src/loci/registry.yaml and the
	# SECTION_INPUTS / CITY_PROBE tables in src/loci/portability.py, never
	# the doc -- a readiness matrix that can be hand-edited will be
	# hand-edited into optimism.
	uv run loci gen-portability

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
	# THE FORECAST LEDGER, after poi-snapshot (inside `chains refresh`) and
	# after storefront-pipeline build, because both the frozen supply and the
	# realized outcome are read off the first-seen ledger and the filings
	# pipeline -- issuing before them would freeze a vintage on last month's
	# evidence and then date it this month.
	#
	# `issue` takes the CURRENT month and is idempotent per
	# (issued_month, model_version): a second run in the same month replaces
	# that month's rows and changes nothing. A NEW model gets a NEW version and
	# its own vintages -- a past vintage is NEVER re-issued with a newer model.
	uv run loci forecast issue --month $$(date +%Y-%m)
	# `score` with no --issued-month scores every vintage whose 12-month horizon
	# has elapsed and has no outcome row yet, so a vintage is scored when its
	# horizon comes due rather than when somebody remembers.
	uv run loci forecast score
	# RETENTION (GTM-163), after `score` and before `recommendations check`:
	# one issue+score cycle adds ~1.4 GB to analysis.forecast and nothing
	# bounded that before this. `forecast prune` deletes PREDICTION rows for
	# vintages older than the newest 3 per model_version, never touching
	# forecast_run/forecast_outcome and never an unscored or open-horizon
	# vintage -- see `loci forecast prune --help`.
	#
	# DRY RUN BY DEFAULT: a bare `make chains-refresh` never deletes forecast
	# rows. Set LOCI_FORECAST_PRUNE_REAL=1 in the environment to flip real
	# deletion on -- the owner decides when.
	uv run loci forecast prune --keep-vintages 3
	# LAST, and the order is load-bearing: the check reads BOTH the first-seen
	# ledger (written by `poi-snapshot`, step 1/4 inside `chains refresh`) and
	# the filing pipeline (written above). Running it first would score every
	# open recommendation against last month's evidence and record a 'none'
	# that this month's data does not support -- and 'none' is a stored
	# observation, not a skip, so the wrong answer would persist.
	uv run loci recommendations check

clean:         ## Drop intermediates and the database (keeps data/raw)
	rm -rf data/interim/* data/processed/* data/loci.duckdb
