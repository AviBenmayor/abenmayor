"""Generate the Linear import CSV and TICKETS.md from a single ticket definition.

Target: the existing Linear project
https://linear.app/avi-benmayor/project/loci-723fa10296fb/overview

Epics map to that project's **Milestones** (E0-E5). Linear has no separate "epic"
object; since Loci is already a Project, milestones are the native fit for
phase-based work and drive the progress bars on the project overview.

    uv run python `loci gen-tickets` (src/loci/tickets.py)
"""
from __future__ import annotations

import csv
import json
import pathlib

ROOT = pathlib.Path(__file__).resolve().parents[2]

# Linear priority: 1 Urgent, 2 High, 3 Medium, 4 Low
U, H, M, L = 1, 2, 3, 4

# 32 raw tags collapse to 14 labels that earn a filter. Keep `critical` and
# `rigor` distinct: `critical` is the P3 coverage-bias chain that can invalidate
# the finding; `rigor` is the checks that decide whether a result is defensible.
LABEL_MAP = {
    "infra": "infra", "decision": "infra", "portability": "infra", "qa": "infra",
    "docs": "docs", "narrative": "docs", "artifact": "docs",
    "ingest": "ingest", "data": "ingest", "data-model": "ingest",
    "data-quality": "ingest", "anchor": "ingest", "control": "ingest",
    "outcomes": "ingest", "universal": "ingest", "nyc": "ingest",
    "grid": "grid",
    "score": "score", "method": "score", "performance": "score",
    "model": "model", "finding": "model", "exploratory": "model",
    "panel": "panel",
    "viz": "viz",
    "validation": "validation",
    "critical": "critical",
    "rigor": "rigor", "risk": "rigor",
    "blocker": "blocker", "cost": "blocker",
    "deferred": "deferred",
    "milestone": "milestone",
}


def map_labels(raw: str) -> str:
    """Collapse raw tags to the canonical label set, order-preserving, deduped."""
    out: list[str] = []
    for tag in raw.split(","):
        mapped = LABEL_MAP[tag.strip()]
        if mapped not in out:
            out.append(mapped)
    return ",".join(out)


LINEAR_PROJECT = "Loci"
LINEAR_PROJECT_URL = "https://linear.app/avi-benmayor/project/loci-723fa10296fb/overview"

EPICS = [
    ("E0 · Foundations", "Repo, charter, schema, credentials. Everything that must exist before data lands.", "Week 0"),
    ("E1 · Ingest and Grid", "All sources landed and normalized; H3 grid built; ACS interpolated. Ships a queryable DB and a first POI-density map.", "Week 1"),
    ("E2 · Access Engine", "Walk graph, multi-source Dijkstra scoring, DNCI. Ships the DNCI map — the first genuinely interesting artifact.", "Week 2"),
    ("E3 · Residual and Panel", "Supply model, residual extraction, LODES panel, growth test with its three mandatory checks. Ships the empirical result and the top-20 list.", "Week 3"),
    ("E4 · Validation and Artifact", "Coverage-bias validation (prediction P3), maps, charts, evidence cards, memo, reproducibility. Ships the public artifact.", "Week 4"),
    ("E5 · Deferred", "Post-week-4: license-date panel, second city, foot traffic, identification strategy.", "Phase 5"),
    ("E6 · Premium Amenities", "Axis 3 — destination amenities people TRAVEL for (padel, spa, boutique fitness). Inverts the daily-needs gap screen: catchment demand-vs-supply over a travel-time trade area, not a walkable prevalence gap. Ships a 'where could a padel court / spa go' site screen.", "Axis 3"),
    ("E7 · Maturity and 2033 Projection", "Axis 4 — the forward extension of Rising (Axis 2). Where each neighborhood sits on its development S-curve today, and where its own trajectory heads by 2033. EXTRAPOLATION with scenario bands and a mandatory backtest — NOT the rejected retail-gap-causes-growth thesis (§0/D1); retail is the dependent read, never the growth predictor.", "Axis 4"),
]

# (epic, title, priority, estimate, labels, description)
T = [
# ------------------------------------------------------------------ E0
("E0 · Foundations", "Write CONTEXT.md project charter", H, 3, "docs",
 "Thesis (residual reformulation), definitions, source registry, method, viz plan, acceptance criteria, threats, phases, open questions.\n\nDONE — CONTEXT.md, 488 lines, 10 sections."),
("E0 · Foundations", "Scaffold repo: package layout, pyproject, Makefile", M, 2, "infra",
 "loci/{sources,grid,score,model,viz}, uv-managed pyproject, Makefile, .env.example, .gitignore.\n\nDONE."),
("E0 · Foundations", "DuckDB schema DDL", M, 3, "infra,data-model",
 "raw / staging / analysis schemas. staging.poi is the normalized contract that src/loci/score consumes — no city-specific columns downstream of staging.\n\nCAVEAT that the DB will not enforce: DuckDB GEOMETRY carries no SRID. Everything stored is EPSG:4326 by convention; metric work must reproject explicitly. Hold this in code.\n\nDONE — src/loci/sql/001_bootstrap.sql, 002_schema.sql. 9 tables verified."),
("E0 · Foundations", "Machine-readable source registry + drift check", M, 2, "infra,data",
 "registry.yaml mirrors CONTEXT.md §3. `loci check-sources` asserts schema validity, budget ceiling, and that every dataset_id in the registry appears in CONTEXT.md — so the human and machine registries cannot drift.\n\nIt caught a real drift on its first run (MTA ridership wujg-7c2s was in the registry, missing from the charter).\n\nDONE."),
("E0 · Foundations", "Drop PostGIS for DuckDB; remove Docker from the critical path", M, 3, "infra,decision",
 "Reversed the original PostGIS choice. The only available image ran emulated (amd64 on arm64) and the 'service path' rationale was speculative.\n\nDuckDB verified end to end: spatial + community h3 extensions, RTREE indexes, ST_Read, read_parquet, and every DDL feature the schema needs. H3 cells stringify to 15 chars, so the CHAR(15) design carried over unchanged.\n\nNo container, no daemon, no emulation penalty.\n\nDONE — see CHECKPOINT decision D9."),
("E0 · Foundations", "Obtain Census API key", H, 1, "infra,blocker",
 "Free and instant: https://api.census.gov/data/key_signup.html\nSet CENSUS_API_KEY in .env. Blocks ACS ingest (E1)."),
("E0 · Foundations", "Obtain Google Places key with a hard call budget", M, 1, "infra,cost",
 "Pro SKU $32/1k, 5,000 free calls/month. Budget 5,000 calls ≈ $0–100.\n\nGUARDRAIL: request ONLY id/name/location/types. Adding ratings or hours reprices to Enterprise ($35/1k); reviews or photos to Enterprise+Atmosphere ($40/1k). Enforce LOCI_GOOGLE_CALL_BUDGET in the client.\n\nNeeded W4, not W1.\n\nDONE 2026-09-02 — src/loci/validation/google_places.py: persisted call ledger, refuses when LOCI_GOOGLE_CALL_BUDGET is unset or exhausted, minimal field mask (id/location/types). `loci validate --dry-run` plans the spend; `--run` executes under the cap. Webmap per-click calls capped by GOOGLE_CLICK_BUDGET (default OFF)."),
# ------------------------------------------------------------------ E1
("E1 · Ingest and Grid", "VERIFY: LODES8 block vintage is 2020 TIGER across all years", U, 2, "data,risk",
 "CONTEXT.md open question #5. If LODES8 uses 2020 blocks for every vintage, the 2002–2023 panel needs no 2010/2020 crosswalk. If it does not, budget a crosswalk before E3.\n\nThis is the cheapest possible check and it de-risks the entire panel. Do it first.\n\nSource: https://lehd.ces.census.gov/data/lodes/LODES8/"),
("E1 · Ingest and Grid", "VERIFY: DCWP Legally Operating Businesses freshness", H, 1, "data,risk",
 "CONTEXT.md open question #6. The portal has shown a stale refresh date (data as of 2023). Confirm the current vintage via the Socrata metadata endpoint.\n\nIf stale: downgrade DCWP to snapshot-only and lean harder on DOHMH as the anchor."),
("E1 · Ingest and Grid", "Overture Places adapter → staging.poi", H, 5, "ingest,universal",
 "GeoParquet via overturemaps-py, NYC bbox. Map Overture categories onto the 15 Loci categories (CONTEXT.md §2.1).\n\nOverture's schema is coarse for personal services — expect the salon/laundromat mapping to be the lossy part, and record mapping confidence in staging.poi.confidence."),
("E1 · Ingest and Grid", "Foursquare OS Places adapter", M, 3, "ingest,universal",
 "Apache-2.0, separate taxonomy from Overture. Used as a cross-check, not as the base layer — FSQ skews toward venues with check-in history, i.e. away from laundromats.\n\nWhy it matters under the gap screen: it is the only free bulk source with fine-grained gym / hardware / urgent-care labels — the top gap types with no government anchor.\n\nBLOCKED 2026-09-02 on access: public S3 bucket retired (holds LICENSE/NOTICE only); data is on the Places Portal (Iceberg token) or the gated Hugging Face mirror. Adapter written (sources/universal/foursquare_places.py, tests pass); set HF_TOKEN after accepting the terms, then `loci ingest --source foursquare_os_places --dry-run` and tighten LEAF_CATEGORY against the reported unmapped leaves.\n\nDONE 2026-09-02 — token obtained, NYC extract cached (821k rows, <1 min), category map rebuilt from the real 1,279-label taxonomy (path-prefix rules for the restaurant/bar/cafe families; Deli, ATM, Doctor's Office and specialist physicians deliberately dropped). FRESHNESS GATE added: corroboration by other sources is <10% for rows last refreshed before 2019 vs 55% for 2026, so only rows refreshed since 2024 load (109k of 191k mapped; 54k canonical). Effect on the gap screen was modest once ghosts were removed: hardware 270→245, fitness 154→138, clinic 148→91."),
("E1 · Ingest and Grid", "OSM Overpass adapter", M, 3, "ingest,universal",
 "Tag vocabulary of record (CONTEXT.md §2.1 table). Also the third opinion on presence.\n\nCarries the project's most dangerous bias — see E4 coverage validation."),
("E1 · Ingest and Grid", "DOHMH restaurant inspections adapter (ANCHOR source)", U, 3, "ingest,nyc,anchor",
 "Dataset 43nn-pn8j. ~30k establishments, near-census of food service — every food establishment is inspected, so within the food tier the true count is effectively known.\n\nThis is the calibration anchor for the whole coverage-bias mitigation (CONTEXT.md §7.1). Treat it as the project's most valuable data asset."),
("E1 · Ingest and Grid", "DCWP licenses adapter", M, 3, "ingest,nyc",
 "Dataset w7w3-xahh. Laundries and other DCWP-licensed categories. Has issuance dates — the raw material for the deferred E5 license panel."),
("E1 · Ingest and Grid", "NYS DOS Appearance Enhancement adapter", M, 2, "ingest,nyc",
 "Dataset y3u4-jbgh. Best available source for nail/hair.\n\nCONSTRAINT: active-only, therefore survivorship-biased. Snapshot enrichment ONLY. Must never be used to construct an openings/closings series — enforce this in the adapter, not just in docs."),
("E1 · Ingest and Grid", "USDA SNAP retailer adapter (ANCHOR for grocery/convenience)", H, 3, "ingest,universal,anchor",
 "USDA SNAP Retailer Locator via its ArcGIS feature service. Near-census of stores that accept SNAP; store type separates Supermarket/Grocery from Convenience by stocking breadth.\n\nWhy: tier 1 is 40% of the index and had no anchor. Its bias runs the OPPOSITE way from OSM (misses non-SNAP stores in affluent areas), which makes it a second calibration curve for the coverage-bias check.\n\nVerified 2026-09-02: 8,052 five-borough rows, lat/lon on every row."),
("E1 · Ingest and Grid", "NYS SLA liquor license adapter (ANCHOR for bars)", H, 3, "ingest,nyc,anchor",
 "Dataset 9s3h-dpkz. Anchor for the bar category, which the DOHMH adapter deliberately does not emit.\n\nMapping is conservative — license descriptions do not say bar. Emits `bar` for Food & Beverage Business, Club, Cabaret, Bottle Club; skips Restaurant (DOHMH) and Additional Bar riders. QUESTIONS.md H-D9 tracks the open mapping question.\n\nCompanion inactive file 6dg3-2z7i makes closures recoverable — a candidate E5 panel.\n\nVerified 2026-09-02: 24,711 NYC rows, 98.5% georeferenced."),
("E1 · Ingest and Grid", "Cross-source POI dedup / entity resolution", H, 5, "ingest,data-quality",
 "The same laundromat appears in Overture, FSQ, OSM and DCWP. Without dedup the DNCI inflates wherever coverage overlaps — which is itself geographically biased, so the error is not random.\n\nApproach: spatial blocking (~25m) + normalized-name similarity, per category. Emit a survivorship record so counts are auditable."),
("E1 · Ingest and Grid", "Build H3 res-9 shoreline-clipped grid", H, 3, "grid",
 "~7,400 cells over NYC's ~778 km². Drop water-only hexes; retain partial hexes with land_fraction for edge normalization (threat §7.7)."),
("E1 · Ingest and Grid", "PLUTO loader + commercial zoning capacity control", U, 5, "ingest,nyc,control",
 "MapPLUTO 26v2. Extract ZoneDist1, CommFAR, ResidFAR, BuiltFAR, UnitsRes, YearBuilt; area-weight onto hexes.\n\nREQUIRED CONTROL, not optional. Without commercial zoning capacity in the supply model the underserved tail fills with park edges, industrial zones and cemetery blocks, and the top-20 list is indefensible on first inspection.\n\nAlso supplies the dasymetric ancillary surface and the development-headroom term."),
("E1 · Ingest and Grid", "MTA transit access control", H, 3, "ingest,nyc,control",
 "Stations 39hk-dx4f, Entrances & Exits 68hr-j2j7, Hourly Ridership wujg-7c2s.\n\nUse ENTRANCES, not station centroids — a station can be 400m of walking from its own far entrance. Ridership captures transit quality: a 12-route complex is not a single-route stop.\n\nCaveat to record: ridership window is 2020–2024, so 2020–21 levels are pandemic-depressed."),
("E1 · Ingest and Grid", "ACS ingest + dasymetric interpolation onto hexes", H, 5, "grid,data",
 "ACS 5-yr tract → H3 via tobler, dasymetric with PLUTO UnitsRes as the ancillary surface. Plain areal weighting would spread population evenly across parks, rail yards and cemeteries.\n\nPropagate MOEs — do not silently treat tract point estimates as exact (threat §7.8)."),
("E1 · Ingest and Grid", "Staten Island leverage check", L, 2, "model,data-quality",
 "CONTEXT.md open question #3. Low-density and car-oriented; may act as high-leverage points in the supply model. Include, but check Cook's distance and report results with and without."),
("E1 · Ingest and Grid", "SHIP W1: POI density map + queryable DB", M, 2, "milestone",
 "Week-1 exit criterion. A crude choropleth of raw POI density per hex. Not the finding — proof the pipeline is real and the joins are right."),
# ------------------------------------------------------------------ E2
("E2 · Access Engine", "Build OSMnx pedestrian walk graph", H, 3, "score",
 "network_type='walk', 4.8 km/h (80 m/min).\n\nExtend the graph BEYOND the city boundary so cross-boundary businesses are reachable where they genuinely are — otherwise every edge hex is spuriously underserved (threat §7.7)."),
("E2 · Access Engine", "Multi-source Dijkstra access engine", U, 8, "score,performance",
 "THE performance-critical design decision. Do NOT compute ~7,400 isochrones.\n\nFor each of the 15 categories, run ONE multi-source Dijkstra seeded from every POI in that category at once, cut off at threshold distance. Nodes within cutoff are 'served'.\n\n15 traversals instead of 7,400 — minutes not hours, and it makes the 5/10/15-min sweep affordable (45 traversals total).\n\nEmits analysis.hex_access."),
("E2 · Access Engine", "Calibrate saturating k_c per category", M, 3, "score,method",
 "s_c = 1 − exp(−n_c / k_c), calibrated so the first reachable establishment scores ≈0.55.\n\nEssentials tighter (k≈1.25 — one grocery is nearly sufficient); food looser (one restaurant in a 10-min walk is thin, not complete). Revisit against observed count distributions. CONTEXT.md open question #2."),
("E2 · Access Engine", "DNCI: weighted geometric mean + unit tests", U, 5, "score,method",
 "DNCI = Π (s_c + ε)^w_c, ε = 0.01.\n\nTHE METHODOLOGICAL CRUX. An arithmetic mean lets a hex with fifty restaurants and no grocery, pharmacy or laundromat score well — precisely the failure the thesis exists to detect. Only the geometric form punishes zeros.\n\nTests must include the adversarial case: 50 restaurants + 0 essentials must score LOW. If that test passes under an arithmetic mean, the test is wrong."),
("E2 · Access Engine", "Run 5/10/15-minute threshold sweep", M, 2, "score",
 "10 min (800m) is the headline. 5 min (400m) and 15 min (1200m) as sensitivity and for comparability with the 15-minute-city literature."),
("E2 · Access Engine", "SHIP W2: the DNCI map", H, 3, "milestone",
 "Week-2 exit criterion and the first genuinely interesting artifact. Sequential palette. Sanity-check against local knowledge before proceeding to E3."),
# ------------------------------------------------------------------ E3
("E3 · Residual and Panel", "Fit the supply model", U, 5, "model",
 "DNCI ~ pop_density + median_hh_income + transit_access + commercial_zoning_capacity + land_fraction + borough FE.\n\nCheck prediction P1: the residual must have meaningful spread. If R² > 0.9 there is nothing left to explain and the thesis has no room to be true — report that honestly rather than tuning until it isn't."),
("E3 · Residual and Panel", "Moran's I + spatial error/lag model", H, 5, "model,rigor",
 "MANDATORY, not optional. Compute Moran's I on residuals; if significant (it will be), re-estimate with pysal spreg and report both.\n\nOLS standard errors on gridded urban data are wrong. Shipping a p-value without this is shipping a p-value you cannot defend."),
("E3 · Residual and Panel", "Residual extraction + opportunity score", H, 3, "model",
 "opportunity = (−u_h)⁺ × transit_access × (ResidFAR − BuiltFAR)⁺.\n\nUnderserved AND transit-connected AND room to build. Any one of the three missing disqualifies the hex."),
("E3 · Residual and Panel", "LODES WAC annual panel loader 2002–2023", H, 5, "panel,data",
 "NY state WAC files, target NAICS 4451/4461/7224/7225/8121/8123/4441/6244. Block-level, 22 vintages.\n\nBlocked on the LODES8 block-vintage verification (E1)."),
("E3 · Residual and Panel", "LODES block → hex apportionment", H, 3, "panel,grid",
 "Areal apportionment of block-level jobs onto H3 cells.\n\nDocument the proxy assumption loudly: LODES counts JOBS, not establishments. A ten-employee supermarket and a one-employee laundromat are not comparable units (threat §7.4)."),
("E3 · Residual and Panel", "Quantify pre-2020 LODES allocation bias", H, 5, "panel,risk",
 "Discovered while resolving the LODES vintage check.\n\nLODES8 puts every year on 2020 blocks, but historical years got there by ALLOCATION, not observation: when a 2010 block splits, each job is assigned to a child block at random with probability proportional to AREA share. Census: 'the allocation is a statistical process and may not result in a distribution of jobs that exactly matches the areal distribution.'\n\nArea-proportional is a poor assumption in NYC — a block splitting into a park half and a commercial half spreads jobs by area, putting employment in the park.\n\nThis is BIAS, not noise: the error concentrates where blocks were split, blocks split where development happened, and development is the outcome variable.\n\nSize the exposure, test whether H3 res-9 aggregation actually absorbs it, and if not restrict the strongest claims to 2020+ observed data. CONTEXT.md threat 7.4(b)."),
("E3 · Residual and Panel", "Validate LODES 2023 against establishment counts", H, 3, "panel,validation",
 "Correlate the 2023 LODES cross-section against 2023 DOHMH/DCWP establishment counts per hex. Report the correlation.\n\nThis is what licenses the jobs→establishments proxy. Without it the whole panel rests on an unexamined assumption."),
("E3 · Residual and Panel", "Assemble outcome variables", H, 5, "outcomes,data",
 "Δlog population, Δlog households (ACS); Δlog ZORI (Zillow, ZIP→hex); permitted residential units (DOB/HPD).\n\nZIP→hex crosswalk by population weighting — CONTEXT.md open question #4. Label rent as the weakest of the four outcomes in the memo and mean it."),
("E3 · Residual and Panel", "Main growth regression (prediction P2)", U, 5, "model,finding",
 "Δy_{h,t0→t1} = β·u_{h,t0} + γ'X_{h,t0} + α_borough + ε, t0=2013 t1=2023.\n\nP2 predicts β < 0 (more negative residual → more subsequent growth). A null or wrong-signed result is a real answer: it would mean gaps persist because they reflect durable demand suppression, not latent opportunity. Report it either way."),
("E3 · Residual and Panel", "Pre-trend test (2003→2013)", U, 3, "model,rigor",
 "Estimate the same spec on the PRIOR decade. If u_2013 also 'predicts' 2003→2013 growth, parallel trends is broken and the causal reading is unavailable.\n\nReport it whichever way it comes out. This is the check a serious reader will ask for first."),
("E3 · Residual and Panel", "Placebo outcome", H, 2, "model,rigor",
 "An outcome with no plausible mechanism — e.g. change in share of population aged 65+ — must return a null. If it doesn't, the specification is picking up generic neighborhood trajectory rather than the retail channel."),
("E3 · Residual and Panel", "MAUP sweep at res 8 and res 10", H, 3, "model,rigor",
 "Re-run the whole chain at two other resolutions; report coefficient stability. If conclusions flip with grid size, say so plainly (threat §7.3)."),
("E3 · Residual and Panel", "Tier-weight sensitivity analysis", M, 3, "model,method",
 "Tier weights (0.40/0.20/0.25/0.15) are judgment, not derived. Sweep plausible alternatives and report whether the top-20 list is stable under reweighting. CONTEXT.md open question #1."),
("E3 · Residual and Panel", "Top-20 list + zoning-artifact audit", U, 3, "finding,qa",
 "Produce the ranked list of transit-rich underserved hexes.\n\nHARD GATE: manually inspect for park edges, industrial zones and cemetery blocks. Any present means the commercial-zoning control failed — fix the model, do not hand-remove the rows.\n\nAlso check it contains ≥3 genuine surprises. A list of only obvious places means the residual isn't doing any work."),
("E3 · Residual and Panel", "Spacing and nearest-missing distance diagnostics", L, 2, "model,exploratory",
 "QUESTIONS.md D5. Two read-only diagnostics the gap screen cannot answer on its own: (1) nearest-neighbour distance between businesses of the SAME category — how clustered each trade is and how often a business has no competitor within a walk; (2) for each gap hex, straight-line distance to the nearest business of its lead-missing category — separates marginal 10-minute gaps from real holes.\n\nDONE 2026-09-02 — `loci spacing` (src/loci/model/spacing.py). Found and fixed on the way: DuckDB ST_Distance_Sphere reads (lat, lon) — decision D16, shared METRES_SQL in db.py."),
("E3 · Residual and Panel", "Residual convergence test", L, 3, "panel,exploratory",
 "QUESTIONS.md T5 — does the gap close on its own?\n\nOver 2002–2023, do hexes with a negative residual at t converge toward their peers by t+k (retail employment growth regressed on the lagged residual, borough FE)?\n\nWhy it matters: if the market already corrects undersupply, the opportunity is TIMING, not location — a different product and a different memo. Cheap once the LODES panel exists; pull forward if W3 has slack, otherwise it slides to Phase 5."),
("E3 · Residual and Panel", "Retail lead/lag timing test", L, 3, "panel,exploratory",
 "QUESTIONS.md T6 — does retail lead or lag rooftops?\n\nCross-correlate annual per-hex changes in LODES retail employment with changes in population at leads and lags of 1–5 years.\n\nWhy it matters: 'retail follows rooftops' is the assumption the whole residual design rests on (D1). This is the one place it gets tested rather than asserted.\n\nCAVEATS to state: ACS 5-year smoothing limits timing resolution to roughly half-decades; LODES counts jobs, not storefronts (M2)."),
("E3 · Residual and Panel", "SHIP W3: empirical result + top-20", H, 2, "milestone",
 "Week-3 exit criterion."),
# ------------------------------------------------------------------ E4
("E4 · Validation and Artifact", "Design stratified coverage validation sample", U, 3, "validation,critical",
 "Prediction P3 and threat §7.1 — the one that can invalidate everything.\n\nOSM/Overture undercount small business in lower-income and immigrant neighborhoods: exactly the areas the thesis flags as underserved. If the undercount is strong there and weak in Park Slope, the 'retail gap' is a data gap wearing a costume.\n\nDraw hexes at random within each income decile, and cross-stratify by foreign-born share (ACS) so borough / immigrant-neighborhood contrasts in the residual (QUESTIONS.md X3) can be separated from coverage bias. Fix n per stratum against the 5,000-call budget before spending anything.\n\nDONE 2026-09-02 — src/loci/validation/sample.py: NTILE(10) on median income among populated hexes, seeded random draw per decile, like-for-like 800 m straight-line counts for Google vs Overture/OSM/anchor. Foreign-born cross-stratification NOT possible yet: hex_demographics has no foreign-born column (add to ACS ingest first). Default plan: 200 hexes × 15 categories = 3,000 calls, inside the free tier."),
("E4 · Validation and Artifact", "Run Google Places ground-truth enumeration", U, 5, "validation,critical,cost",
 "Enumerate ground truth for the sampled hexes. Fields: id/name/location/types ONLY — anything more reprices the SKU.\n\nEnforce the call budget in code. Populate analysis.coverage_validation."),
("E4 · Validation and Artifact", "DOHMH-anchored undercount calibration", U, 5, "validation,critical",
 "Within the food tier the true count is effectively known (DOHMH is a near-census). Measure OSM/Overture discrepancy vs DOHMH per hex, then use that curve to estimate expected undercount in the other tiers where no census exists.\n\nThis is the strongest available mitigation and it costs nothing extra."),
("E4 · Validation and Artifact", "Coverage-bias chart", U, 2, "viz,critical",
 "Undercount rate by income decile. NOT an appendix item.\n\nIf the finding survives this chart, the chart is the most persuasive artifact in the set. If it doesn't, this chart is how the project learns that honestly rather than shipping a bias as a finding."),
("E4 · Validation and Artifact", "PMTiles export + MapLibre map", H, 5, "viz",
 "H3 choropleth, static hosting, no server. Layer toggle between DNCI (sequential) and residual (DIVERGING — zero is a real midpoint, not an arbitrary one).\n\nLoad the `dataviz` skill before writing chart code."),
("E4 · Validation and Artifact", "Bivariate transit × residual map", H, 3, "viz",
 "3×3 bivariate palette. This is the map that states the thesis in one image: where transit-rich and underserved overlap."),
("E4 · Validation and Artifact", "Per-category radar small multiples", M, 3, "viz",
 "15-spoke radar per top-20 hex. Answers 'what specifically is missing here — grocery, or salons?' Turns a score into an actionable observation."),
("E4 · Validation and Artifact", "Scatter: residual@t0 vs growth t0→t1", H, 2, "viz",
 "Fitted line + CI, borough-colored. The visual statement of P2."),
("E4 · Validation and Artifact", "4–6 neighborhood evidence cards", H, 5, "artifact,narrative",
 "Narrative + inset map per selected hex cluster. Does the mechanism look real on the ground? This is what converts a coefficient into something a reader believes."),
("E4 · Validation and Artifact", "Methodology memo", H, 5, "docs,artifact",
 "The document a skeptic attacks and you defend. Must state plainly: the residual design reduces but does not eliminate endogeneity (§7.2); no instrument is used; what the pre-trend test showed.\n\nClaiming cleaner identification than exists is the fastest way to lose an investment reader."),
("E4 · Validation and Artifact", "Fresh-clone reproducibility test", H, 3, "infra,qa",
 "Acceptance criterion C: fresh clone → `make nyc` → outputs in <30 min on a laptop. Pinned deps, documented lineage.\n\nAlso assert loci/score/ contains no NYC-specific column names — the portability guarantee from CONTEXT.md §10."),
("E4 · Validation and Artifact", "SHIP W4: public artifact", U, 2, "milestone",
 "Week-4 exit criterion: public map + memo + evidence cards."),
# ------------------------------------------------------------------ E5
("E5 · Deferred", "DCWP license issue/expiry panel reconstruction", L, 8, "panel,deferred",
 "Establishment-level openings/closings from DCWP license dates — a true establishment panel rather than the LODES jobs proxy.\n\nDeferred from W3 because it is ~2 weeks of data engineering with real survivorship handling. Only NYS DOS is unusable for this; DCWP is genuinely dated."),
("E5 · Deferred", "Extract universal interface; run a second city", L, 8, "portability,deferred",
 "`loci run --city chicago` on universal sources only (Overture, FSQ, LODES, ACS, OSM, GTFS), with a coverage warning where NYC-grade local data has no analogue.\n\nThe half-day spent in E0 keeping loci/score/ city-agnostic is what makes this possible rather than a rewrite."),
("E5 · Deferred", "Foot-traffic outcome", L, 5, "outcomes,deferred,cost",
 "SafeGraph/Placekey-class data, $200–400 of the ~$400 unspent headroom. Shifts the outcome from 'did people move here' to 'did people start going here'. Nice-to-have; not load-bearing.\n\nSpend the headroom on enlarging the E4 validation sample FIRST — that has higher marginal value because it defends against the threat that can kill the project."),
("E5 · Deferred", "Identification strategy: quasi-experimental variation", L, 8, "model,deferred",
 "Addresses threat §7.2 properly. Candidates: historic rezonings, or transit shocks such as the L-train shutdown, as sources of variation in retail supply plausibly exogenous to neighborhood trajectory.\n\nOut of scope at 4 weeks. This is what a v2 would need to make a genuinely causal claim."),
# ------------------------------------------------------------------ E6  (Axis 3 — premium / destination amenities)
("E6 · Premium Amenities", "Charter the premium-amenity axis (CONTEXT §11)", H, 2, "docs,decision",
 "Owner add 2026-09-02: screen NYC for where a PREMIUM, destination amenity could open — padel courts and spa/wellness studios first.\n\nWhy this needs its own charter section and cannot reuse the daily-needs gap screen: the two goods behave oppositely.\n • Daily needs are convenience goods — consumed often, near-zero willingness to travel, so the geography is the 800 m walk and the screen is 'present in ≥80% of walkable peers, absent here.'\n • Premium amenities are DESTINATION goods — consumed occasionally, high ticket price, people will drive/transit 15–30 min for them (the owner's own premise). They are RARE by nature, so a prevalence-gap screen would flag almost everywhere and mean nothing.\n\nSo the method inverts to a classic trade-area / gravity site-selection model: a travel-time CATCHMENT with enough qualifying premium demand but little or no supply within that catchment, plus a feasible large-format site. Document it as CONTEXT §11 and CHECKPOINT D22. This is Axis 3, parallel to Axis 1 (Investability, invest.py) and Axis 2 (Rising, rising.py) — NOT a return to the rejected residual-growth thesis (D1)."),
("E6 · Premium Amenities", "Define the premium-amenity bundle + demand-target per category", H, 3, "score,method",
 "Padel and spa are the two named anchors; extend to the destination-amenity family that shares the travel-for-it behavior, each kept as its OWN category because catchment size, demand target and site needs differ: padel, spa / day-spa, med-spa, pilates / reformer, boutique fitness / boxing, climbing gym, bathhouse / sauna, golf & sports simulator.\n\nEach category carries (a) its demand TARGET — not raw population: padel skews affluent + athletic + 25–44; med-spa skews affluent women 30–55; climbing skews younger + college-educated — and (b) a nominal catchment travel time and site footprint. These are judgment calls, stated explicitly and tunable, exactly like the daily-needs tier weights and the invest.py ECON minimums (D18). Emit the bundle as data (a PREMIUM dict mirroring ECON), not hard-coded in the scorer."),
("E6 · Premium Amenities", "Ingest premium-amenity supply + Google-validate (mandatory here)", H, 5, "ingest,universal,validation",
 "These amenities are OUTSIDE the daily-needs 15, so they need their own supply layer. Sources: OSM (padel = leisure=pitch + sport=padel; spa = leisure=spa / shop=beauty+beauty=spa; climbing = sport=climbing; sauna = leisure=sauna), Foursquare leaves (Spa, Pilates Studio, Climbing Gym, Boxing Gym, Gym and Studio subtypes), Google Places for ground truth.\n\nWhy Google validation is load-bearing here, not optional as it is for daily needs: padel barely existed before 2022 and boutique studios open fast, so OSM/Foursquare snapshots undercount them SEVERELY and unevenly. A padel 'gap' is far more likely to be a data gap than a daily-needs gap is (threat: the §7.1 coverage bias, but worse). Validate every candidate site's catchment against Google + a manual web check before it ships. Reuse the budget-guarded validation client (src/loci/validation/)."),
("E6 · Premium Amenities", "Travel-time catchment engine (drive + transit isochrones)", H, 8, "score,performance",
 "Replaces the 800 m walk ring with a per-amenity travel-time CATCHMENT — the load-bearing modeling choice for this axis, and the owner's core premise ('people will travel longer').\n\nBuild drive-time isochrones (car network) unioned with transit-time where the amenity is transit-oriented (a Manhattan spa is reached on foot/subway; an outer-borough padel box is reached by car with parking). Default 15 min, and because willingness-to-travel is ASSUMED not measured, sweep 10 / 15 / 20 / 30 min and report how the site ranking moves — the sensitivity IS the honesty here. Reuse the OSMnx graph machinery from E2; the drive network and isochrone reach are the new parts. Emits a catchment membership table (site/hex → reachable population + supply)."),
("E6 · Premium Amenities", "Premium demand pool per catchment", H, 5, "model",
 "Score each catchment's DEMAND — not raw homes (that is the daily-needs driver) but a premium demand pool: population weighted toward the top income deciles, the category's target age band, and college/education share (which D20 already computes and found correlated 0.72 with income). Per-category weighting from the demand TARGET defined in the bundle ticket.\n\nRe-use hex_demographics (income, renter) + the ACS momentum module's age/education pulls (model/momentum.py). Output: qualifying-demand headcount and $ per candidate catchment, comparable across amenities."),
("E6 · Premium Amenities", "Large-format feasibility gate", M, 5, "model,control",
 "The invest.py feasibility gate (D18) but re-tuned for destination formats. A padel court needs ~1,000+ m² and height (warehouse, parking deck, flex/industrial — often NOT a ground-floor retail bay); a day-spa needs mid-size retail or upper-floor; a climbing gym needs a tall shell. So the PLUTO test changes from 'any CommFAR>0 storefront' to lot size + floorplate + a zoning district that permits commercial recreation / personal-service, plus vacancy/industrial-conversion candidates.\n\nWithout this the screen recommends amenities onto lots where they physically or legally cannot go — the D3 zoning-artifact failure in a new costume. Gate each candidate site on a buildable/leasable large-format space before it can rank."),
("E6 · Premium Amenities", "Premium opportunity score + ranked site list", H, 5, "model,finding",
 "Combine: opportunity = qualifying demand pool in the catchment − existing supply reachable within that catchment, gated on a feasible large-format site, ranked per amenity.\n\nThree threats to state plainly on the list, because a reader will raise them:\n • Supply undercount is worse for these new categories (padel especially) — every top site must survive Google + manual validation or it is presumed a data gap, not an opportunity.\n • Willingness-to-travel is assumed; the catchment radius is the biggest lever, so report the ranking under the 10/15/20/30-min sweep, not a single radius.\n • National-chain pipeline (Life Time, Equinox, Padel Haus, etc.) may already have a site under LOI — outside the data, flagged as manual diligence per top pick.\n\nProduces the padel and spa shortlists the owner asked for."),
("E6 · Premium Amenities", "SHIP: 'Where could a padel court / spa go?' map layer", H, 3, "viz,milestone",
 "Axis-3 deliverable, parallel to the invest/rising buy-list artifacts. A map layer (toggle per amenity) showing travel-time catchments shaded by UNMET premium demand, with feasible large-format sites pinned and each top site carrying its demand pool, nearest existing supply, and the validation result. Load the `dataviz` skill before writing chart code."),
# ------------------------------------------------------------------ E7  (Axis 4 — maturity curve + 2033 projection; forward extension of Rising)
("E7 · Maturity and 2033 Projection", "Charter the maturity + projection axis (CONTEXT §12), honestly vs §0/D1", H, 3, "docs,decision",
 "Owner add 2026-09-02, two linked questions: (1) where is each neighborhood on its MATURITY curve today, and (2) where could growth get to by 2033 — how do we project it.\n\nThis is the forward extension of Axis 2 (Rising, D19/D20/D21), and it MUST be framed to not revive the project's central rejected result. Be explicit in CONTEXT §12:\n • DEAD and staying dead (§0/D1): 'the retail gap/residual at t0 predicts subsequent residential growth' — β was wrong-signed (+0.069), pre-trends broken. This axis never uses the retail residual as a growth predictor.\n • LEGITIMATE and different: locating a neighborhood on a development S-curve from its OWN observed multi-metric history (income, college, rent, permits, jobs), then EXTRAPOLATING that trajectory. The pre-trend finding — that these places are on a development cycle — is precisely what licenses extrapolation.\n • The honesty is in the caveats: extrapolation assumes the frontier keeps diffusing and no macro shock intervenes. D21 already caught ENY rents COOLING to +1.9%/yr — trajectories bend, so the output is scenario bands, never a point forecast, and it is credible only if it passes the backtest ticket.\n\nRetail (Loci's core product) attaches at the END as the dependent read: given a projected 2033 demand surface, today's Axis-1/Axis-3 sites can be re-scored forward. Write CONTEXT §12 + CHECKPOINT D23."),
("E7 · Maturity and 2033 Projection", "Assemble the multi-decade neighborhood trajectory panel", H, 8, "ingest,panel,data",
 "momentum.py (D20) pulled only two points (2013 & 2023). Staging and projection need a real time series per NTA. Assemble: decennial 2000 + 2010, ACS 5-yr 2009/2013/2018/2023 (real HH income via B19025/B11001, college share B15003, tenure, age bands), LODES WAC 2002–2023 (already downloaded), Zillow ZORI/ZHVI 2000– (D21), DOB/HPD permit pipeline by year.\n\nDeflate every dollar series to 2023 real (CPI ×1.308 for 2013→2023 per D20 — extend the factor to each vintage) or the trend is mostly inflation. Aggregate each vintage to 2020 NTA via that year's tract centroids (the momentum.py gazetteer method). Output: analysis.nta_trajectory, one row per NTA per year per metric. This is the raw material for BOTH the maturity classifier and the projection."),
("E7 · Maturity and 2033 Projection", "Neighborhood maturity-stage classifier", H, 5, "model,method",
 "Place each NTA on the development S-curve. THE methodological point: stage is defined by LEVEL and RATE and ACCELERATION (1st + 2nd derivative) of the panel metrics, not by level alone — that is what separates a maturity model from a static wealth map. A high-income but decelerating neighborhood is 'maturing'; high-income and still accelerating is 'rising'.\n\nStages: pre-frontier/dormant (low level, flat) → emerging (income accelerating, college still low, first permits — where ENY sits: +42% income but college only 9→14%, D21) → rising (income+college both climbing fast, rent + permit boom) → maturing (high level, growth decelerating — Williamsburg now) → mature/saturated (high, flat or declining — the 5 rich Manhattan NTAs in real decline, D20). Spatial adjacency to the already-risen frontier is a feature (gentrification diffuses to neighbors). Output: each NTA's stage + a 0–1 position along the curve."),
("E7 · Maturity and 2033 Projection", "Frontier-diffusion map: where the edge moved, where it goes next", H, 5, "model,viz",
 "Half of 'where could growth get to' is spatial. Trace the observed gentrification frontier 2000→2023 — Williamsburg → Bed-Stuy → Bushwick → Crown Heights → Ocean Hill → East New York (D20 already found this path) — as a datable wave, and identify the not-yet-risen neighborhoods ADJACENT to today's rising edge as the mechanistic next steps.\n\nThis is the most communicable form of the forecast and the one most tied to an actual mechanism (diffusion to neighbors), so it anchors the more model-driven projection. Report the frontier's measured pace (blocks/decade) — that pace is what sets the 2033 reach."),
("E7 · Maturity and 2033 Projection", "2033 trajectory projection with scenario bands", H, 8, "model,finding",
 "Project each NTA's income / college / rent to 2033. Two complementary methods, reported together:\n • Per-metric LOGISTIC (saturating) extrapolation — logistic not linear, because a neighborhood cannot gentrify past 100% and linear extrapolation of a hot decade is the classic forecasting error.\n • Stage-transition (Markov) roll-forward — estimate P(stage→stage per decade) from the historical panel, then advance each NTA one step to 2033, giving a probabilistic stage.\n\nOutput is SCENARIO BANDS, never a point estimate: continued-diffusion / stall / reversal, motivated by the live evidence that trajectories bend (ENY rents cooled to +1.9%/yr post-2022, D21). Also produce the analogue read — for each emerging NTA, the already-matured NTA it most resembles at the same stage (ENY-2023 ≈ Bushwick-2011?) and that analogue's realized path as an interpretable forecast."),
("E7 · Maturity and 2033 Projection", "Backtest the projection (fit 2000→2013, predict 2013→2023)", U, 5, "model,rigor",
 "The load-bearing credibility check — the analogue to E3's pre-trend/placebo rigor, and the reason this axis is not astrology. Fit the classifier + projection on data through 2013 ONLY, project 2013→2023, and compare to what actually happened. If the model cannot retrodict the Bushwick/Crown Heights/ENY arc it demonstrably cannot forecast 2033, and the memo must say so.\n\nReport out-of-sample error by stage (emerging neighborhoods are the hardest and the most important). This ticket gates whether the 2033 numbers ship as a forecast or only as a scenario illustration."),
("E7 · Maturity and 2033 Projection", "Bridge to the product: forward-looking demand for Axes 1 & 3", M, 5, "model",
 "Close the loop WITHOUT reviving D1. Take the projected 2033 demand surface (population/income/education by scenario) and re-score the Axis-1 investability gaps and Axis-3 premium sites against it, so a site that is marginal on today's demand but sits in a neighborhood projected to mature by ~2030 becomes visible as a forward bet.\n\nGuardrail, stated in code and memo: retail is the DEPENDENT variable of the projection (projected rooftops/income drive projected demand), never the predictor of growth. The moment a retail gap is used to predict neighborhood growth, this has become the rejected thesis again."),
("E7 · Maturity and 2033 Projection", "SHIP: maturity + 2033 projection artifact", H, 3, "viz,milestone",
 "Axis-4 deliverable. Per-neighborhood: its position on the S-curve, its 2033 scenario cone (continued/stall/reversal), and its nearest historical analogue; plus the frontier-diffusion map showing where the edge goes next. Every projected number carries its backtest error. Load the `dataviz` skill before writing chart code."),
]

def generate() -> tuple[int, int, int]:
    """Write docs/TICKETS.md and the Linear exports. Returns (issues, milestones, points)."""
    rows = []
    for epic, title, prio, est, labels, desc in T:
        rows.append({
            "Title": title,
            "Description": desc,
            "Status": "Backlog",
            "Priority": prio,
            "Estimate": est,
            "Labels": map_labels(labels),
            "Project": LINEAR_PROJECT,
            "Milestone": epic,
        })

    out_csv = ROOT / "docs" / "linear-import.csv"
    with out_csv.open("w", newline="") as fh:
        w = csv.DictWriter(fh, fieldnames=["Title", "Description", "Status", "Priority",
                                           "Estimate", "Labels", "Project", "Milestone"])
        w.writeheader()
        w.writerows(rows)

    pname = {1: "Urgent", 2: "High", 3: "Medium", 4: "Low"}
    md = ["# Loci — Ticket Plan",
          "",
          "Generated by ``loci gen-tickets` (src/loci/tickets.py)`. Import file: [`linear-import.csv`](./linear-import.csv).",
          "",
          f"**Target:** [{LINEAR_PROJECT} project in Linear]({LINEAR_PROJECT_URL})",
          "",
          "**Mapping.** Linear has no separate *epic* object. Because Loci already exists as a "
          "Project, the epics below map to that project's **Milestones** — the native fit for "
          "phase-based work, and what drives the progress bars on the project overview.",
          "",
          f"**{len(EPICS)} epics · {len(T)} issues · {sum(r['Estimate'] for r in rows)} points**",
          "",
          "| Epic | Issues | Points | Window |",
          "|---|---|---|---|"]
    for name, _, window in EPICS:
        sel = [r for r in rows if r["Milestone"] == name]
        md.append(f"| {name} | {len(sel)} | {sum(r['Estimate'] for r in sel)} | {window} |")

    for name, blurb, window in EPICS:
        md += ["", "---", "", f"## {name}", "", f"*{window}* — {blurb}", ""]
        for r in (r for r in rows if r["Milestone"] == name):
            md.append(f"### {r['Title']}")
            md.append(f"`{pname[r['Priority']]}` · `{r['Estimate']} pts` · `{r['Labels']}`")
            md.append("")
            md.append(r["Description"])
            md.append("")

    (ROOT / "docs" / "TICKETS.md").write_text("\n".join(md) + "\n")

    # Machine-readable form, for pushing through the Linear MCP connector.
    (ROOT / "docs" / "linear-tickets.json").write_text(json.dumps({
        "project": LINEAR_PROJECT,
        "project_url": LINEAR_PROJECT_URL,
        "milestones": [{"name": n, "description": d, "window": w} for n, d, w in EPICS],
        "issues": rows,
    }, indent=2) + "\n")
    return len(rows), len(EPICS), sum(r["Estimate"] for r in rows)
