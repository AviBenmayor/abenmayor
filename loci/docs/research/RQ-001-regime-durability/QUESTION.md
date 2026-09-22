# RQ-001 — Regime Durability

Scaffolded 2026-09-22 by `loci research new`. Fill every section from the interview and
the seed before marking `question: done` in STATUS.yaml — this file's job is to make
SEED.yaml's constraints legible to a reader who will never open the YAML.

## Question as asked

"How often does the landscape of a neighborhood fully shift - what causes it? what im asking here is if a restaurant were to purchase a storefront in a neighborhood, how long should they anticipate for the favorable conditions to last? this should take into account neighborhood information, foot traffic change over time, favorable macroeconomic conditions (if thats a true factor)."

## Interview rulings

- Outcome = composite regime combining demand (foot traffic, residents/workers, income), supply (restaurant density/saturation), and cost (rent).
- Tenure = answer both owner (property-purchase perspective) and tenant (lease-holder perspective) separately.
- Unit of analysis = address trade area (Loci address grain), aggregated up for reporting purposes.
- Answer form = base rate (citywide distribution of favorable-regime duration) + ranked drivers of regime exit + per-site expected-duration function.
- History = two-tier: ZIP-level data 1994→present for long base rate; address-level panel ~2010→present for calibration and per-site scoring.
- Macro enters only through free series (FRED/BLS: NYC unemployment, restaurant employment, rates, CPI food-away-from-home, NBER recessions, COVID window) and is tested as a hypothesis, not assumed.
- Spend = free sources pulled in full with no caps/windows/samples; paid historical foot-traffic source scoped with a quote only, nothing bought without an explicit owner budget ruling.
- Shift rule = both data-driven regime model (Markov/HMM clustering) and fixed-threshold rule, compared side by side; neither alone is the answer.
- Framework = folder + template + CLI gate (`loci research check`) to ensure reproducibility and drift detection.
- Validation = all four methods (out-of-time backtest vs median-for-all baseline, named-neighborhood urban-planner check, contrarian + statistician verdict, operator-site spot check).
- Session deliverable = framework + v0 answer (provisional, labeled).
- Publishing = executed .ipynb in repo only (no HTML artifact, no Notion mirror for this question).
- Concept scope = all full- and limited-service restaurants, with breakdown by Loci category where sample supports it.
- Baseline for "favorable" = top tercile among NYC trade areas in the same year.
- Linear = new "Research questions" milestone in the Loci project with RQ-001 as parent issue.
- Mid-session ruling: ingest ALL free data gaps this session (macro, Zillow ZORI/ZHVI, LODES, ACS panel, PLUTO vintages) with no rolling windows or caps.

## Definitions

**Favorable regime**: Composite of three standardized pillars (within each year, citywise):
- Demand pillar: foot traffic, resident and worker density, income.
- Supply pillar: restaurant density and saturation by segment.
- Cost pillar: rent (ZORI/ZHVI proxies, ACS rent).
- A trade area is "favorable" when its composite score falls in the top tercile (≥ 66th percentile) among all NYC trade areas that same year.

**Full shift**: A transition out of a favorable regime, measured two ways. A spell is a contiguous run of favorable years. An exit is "full" when:
1. **Data-driven regime model**: Markov or HMM clustering detects a regime-state change (e.g., emerging → favorable → saturated → declining).
2. **Threshold rule**: Trade area exits the top tercile (falls below the 66th percentile); re-entry requires ≥ 0.70 score; exit requires < 0.60 score; persistence requires 2-year stability.
These two definitions are run independently and compared; results are reported for both, with sensitivity noted.

**Duration**: Years from favorable-regime entry to exit (or to the data end if ongoing). Durations are right-censored survival data; ongoing regimes are never dropped and the censoring flag is always stated.

**Owner (property-purchase) view**: Emphasizes property-value stability, neighborhood asset quality, and long-term appreciation; weights all three pillars equally.

**Tenant (lease-holder) view**: Emphasizes customer accessibility, cost certainty, and lease horizon; weights cost pillar more heavily than owner view.

**Restaurants**: All full-service and limited-service establishments in Loci categories (disaggregated where sample ≥ n). Definition driven by NYC Department of Health food-service licensing and Loci's own category taxonomy.

**Censoring**: A regime is censored (ongoing) if the data ends while it remains favorable. Censoring is always reported; Kaplan–Meier survival curves mark censored observations.

## Tiers / unit

**Unit of analysis**: Address trade area (Loci's address-grain definition), aggregated up for citywide reporting.

**Tier 1 — ZIP-level (long panel, base rate)**:
- Data: ZIP-level aggregates from Census Bureau CBP (1994–present), ZBP (1998–present), ACS 5-year panels (2005–present).
- Grain: ZIP code.
- History depth: 1994 to present (three decades).
- Purpose: Citywide base-rate distribution of favorable-regime duration; baseline for all comparison.
- Outcome: KM survival curve + median + IQR (censoring share noted).

**Tier 2 — Address-level (recent panel, calibration and per-site)**:
- Data: Address-level restaurant presence (Loci POI truth), foot traffic (from sourced panels or quoted via paid sources), ACS / PLUTO (rents, property value, building traits).
- Grain: Address (Loci's trade-area key).
- History depth: ~2010 to present (16 years, limited by foot-traffic data availability).
- Purpose: Calibrate the regime model at fine grain; generate per-address expected-duration scores; segment by restaurant type.
- Outcome: Fitted regime model + per-address scores; validation backtests.

## Out of scope

- **Causality**: This RQ measures correlation and co-occurrence of regime transitions with macro and local shocks; it does not establish causal chains. Interpretation is restricted to "what shifted" and "when," not "why."
- **Gentrification or displacement dynamics**: Understanding neighborhood change through the lens of gentrification/displacement is a separate research question; this RQ focuses narrowly on favorability for restaurant operations.
- **Single-location or anecdotal validation**: While operator-site spot checks are part of validation, this RQ does not deliver building-by-building advice; per-site function outputs are for portfolio-level ranking, not individual site decisions.
- **Paid data sources beyond quotes**: This session quotes a paid foot-traffic source but does not ingest it; future sessions may incorporate if owner budget-approval arrives.
- **Non-restaurant hospitality or food service**: Bars, bakeries, food trucks, ghost kitchens, and non-restaurant food service are excluded from the baseline; if a related question arises, it goes to a new RQ ticket.
- **Forward prediction beyond model training window**: The regime model is trained on historical data; projection beyond the most recent year is flagged as out-of-sample and requires separate validation (ticketed as future work).
- **Forecasting demand shocks or black-swan events**: The model captures historical patterns; predicting novel events (pandemic, war, recession) is a risk-modeling task, not a regime-durability question.
