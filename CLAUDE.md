# CLAUDE.md - AI Assistant Guidelines

This document provides context for AI assistants working with this repository.

## Repository Overview

This is a personal projects repository holding several independent projects, one per
top-level directory: `agents/`, `alpha_research/`, `arbitrage/`, `claude-beacon/`,
`dashboard/`, `habit_tracker/`, `hearth/`, `loci/`, `mag/`, `mta_time/`, `notchopped/`,
`professor/`.

Two are documented in detail below:

1. **MTA Train Time Display** (`mta_time/`) - Real-time NYC subway arrival display for Graham Avenue L train station
2. **Arbitrage Scanner** (`Arbitrage/`) - Prediction market arbitrage detection system for Polymarket and Kalshi

> The per-project detail in this file covers only those two and is otherwise stale. The
> **Cross-Project Standards** below apply to all projects and are the part to follow for
> anything new.

---

## Cross-Project Standards

Apply to every new project here. Established 2026-09-01 while building `loci/`.

### Repository structure — three directories, named by audience

Exactly three top-level directories. If a fourth seems necessary it almost certainly
belongs inside one of these.

```
<project>/
├── README.md            # the ONLY markdown file at root
├── pyproject.toml       # + uv.lock, Makefile, .env.example, .gitignore
├── docs/                # what humans read
├── src/<pkg>/           # the code, including config and SQL as package data
└── data/                # what machines make — gitignored
```

- **One markdown file at root.** `README.md`, and it points at `docs/`.
- **Config lives with the code that reads it** — `src/<pkg>/registry.yaml`, not a `conf/`
  directory holding a single file.
- **SQL and other resources are package data** — `src/<pkg>/sql/`, not a sibling `db/`.
- **Loose scripts become CLI subcommands.** `myproj check-sources`, never
  `python ops/check_sources.py`. This is the rule that eliminates the `ops/` junk drawer.
- **Use `src/` layout**, not a package at repo root — prevents importing the repo directory
  instead of the installed package.
- **Never use two names that differ by one letter and mean unrelated things** (`db/` vs
  `data/` was a real mistake). Name a directory for who or what consumes it.

### The document trio

Three documents, three lifetimes. Do not merge them.

| File | Holds | Changes |
|---|---|---|
| `docs/CONTEXT.md` | Charter — the *what and why*. Goal, constraints, method, threats to validity, acceptance criteria, open questions. | Rarely, deliberately |
| `docs/CHECKPOINT.md` | State — the *where we are*. Phase, blockers, decision log, session log, next actions. | Every session |
| `docs/TICKETS.md` | Work breakdown. **Generated** — never hand-edited. | Regenerate |

**Read `docs/CHECKPOINT.md` at the start of every session. Update it at the end of every
session.** If a project has one, it is the first file to open.

`CHECKPOINT.md` must contain:

- **Decision log** — append-only, dated, each entry stating what was decided **and why**,
  so a later session does not relitigate it. When a decision is reversed, mark the old
  entry *superseded* rather than deleting it; the reasoning is the value.
- **Blockers table** — each row carries the concrete unblocking action, not just the
  blocker.
- **Environment table** — what is installed, missing, or authenticated.
- **How to resume** — the literal commands.

### Linear

- If the project already exists in Linear, **epics are project Milestones, not Projects.**
  Creating a Project per epic fragments the workspace.
- **Generate tickets from code, never by hand.** One definition list emits `docs/TICKETS.md`,
  `docs/linear-import.csv`, and `docs/linear-tickets.json`. The JSON is the payload for
  pushing through the Linear MCP connector.
- **Ticket descriptions carry the reasoning, not just the task.** "Use a geometric mean" is
  a worse ticket than one explaining that an arithmetic mean would conceal the exact
  failure the project exists to detect.
- **Reserve Urgent** for load-bearing items: the checks that decide whether the work is
  valid, and cheap verifications that de-risk large downstream commitments.
- **MCP servers connected mid-session are invisible until Claude Code restarts.** If Linear
  tools are missing, check `claude mcp list` — a `✔ Connected` server whose tools do not
  appear means restart, not reconfigure.

### Verification habits

- **Verify before committing to a dependency, not after.** Probe the real capability —
  extensions, schema features, API response shape — in a throwaway script before designing
  around it.
- **Machine-check the docs against the code.** Wherever a human-readable table mirrors a
  machine-readable file, write the drift check. It catches real errors.
- **Enforce spend budgets in code**, not in comments, and give anything that costs money or
  writes externally a `--dry-run` path.
- **Don't trust a service the instant it accepts connections.** Init scripts can still be
  running; wait on a real sentinel (an expected table), not just a readiness ping.

## Project Structure

```
abenmayor/
├── mta_time/                 # Node.js MTA train display
│   ├── index.js              # Main terminal display app
│   ├── web-server.js         # Web interface server (port 3000)
│   ├── simple-display.js     # Minimal single-line output
│   ├── lib/
│   │   └── mta-feed-mapper.js # Utility for MTA API endpoints
│   ├── config/
│   │   └── mta-feeds.yaml    # MTA feed configuration
│   ├── package.json          # Node.js dependencies
│   └── setup.sh              # Automated setup script
│
├── Arbitrage/                # Python arbitrage scanner
│   ├── cli.py                # CLI interface
│   ├── config.py             # Configuration settings
│   ├── polymarket.py         # Polymarket API client
│   ├── kalshi.py             # Kalshi API client
│   ├── market_discovery.py   # Market scraping & LLM matching
│   ├── market_matcher.py     # OpenAI-based market matching
│   ├── price_monitor.py      # Continuous price monitoring
│   ├── arbitrage_engine.py   # Arbitrage calculation
│   ├── notifier.py           # Email notifications
│   ├── data/                 # CSV data storage
│   └── requirements.txt      # Python dependencies
│
└── README.md                 # Repository description
```

## Development Workflows

### MTA Train Time Display (Node.js)

**Setup:**
```bash
cd mta_time
npm install
cp .env.example .env  # Add MTA_API_KEY if needed
```

**Run Commands:**
```bash
npm start          # Terminal display with 30-second updates
npm run dev        # Development mode with auto-reload (nodemon)
npm run simple     # Minimal single-line output
npm run web        # Web server on port 3000
```

**Testing:**
```bash
node test-mapper.js           # Test MTA Feed Mapper
node check-l-metropolitan.js  # Test L train data
node check-f-train.js         # Test F train data
```

### Arbitrage Scanner (Python)

**Setup:**
```bash
cd Arbitrage
pip install -r requirements.txt
# Set environment variables: OPENAI_API_KEY, SENDER_EMAIL, SENDER_PASSWORD, RECIPIENT_EMAIL
```

**Run Commands:**
```bash
python cli.py discover   # Run market discovery (scraping + LLM matching)
python cli.py monitor    # Run continuous price monitoring
python cli.py run-all    # Run discovery then monitoring
```

## Key Conventions

### General
- Both projects use MIT License
- Environment variables for sensitive configuration (API keys, credentials)
- Data files stored in dedicated directories (`data/` for Arbitrage)

### MTA Project (JavaScript)
- ES6+ JavaScript with CommonJS modules (`require`)
- Node.js 18+ runtime
- YAML for configuration files
- Protocol Buffers for MTA GTFS-Realtime data parsing
- Function naming: camelCase (`getNextTrain`, `displayTrainInfo`)

### Arbitrage Project (Python)
- Python 3.11+ with type hints
- Class-based design with clear separation of concerns
- CSV files for data persistence
- Configuration via `config.py` module
- OpenAI GPT for intelligent market matching

## External APIs

### MTA Train Time Display
- **MTA GTFS-Realtime API**: Real-time subway data
  - Feeds documented in `config/mta-feeds.yaml`
  - API key optional for v2.0.0+
  - Rate limits: 30-second update interval recommended

### Arbitrage Scanner
- **Polymarket Gamma API**: Prediction market data
  - Base URL: `https://gamma-api.polymarket.com/`
  - No authentication required
- **Kalshi Elections API**: Prediction market data
  - Base URL: `https://api.elections.kalshi.com/v1/`
  - No authentication required
- **OpenAI API**: GPT-5-mini for market matching
  - Requires `OPENAI_API_KEY` environment variable
  - Used for intelligent market matching with confidence scores

## Important Configuration Files

| File | Purpose |
|------|---------|
| `mta_time/.env` | MTA API key (optional) |
| `mta_time/config/mta-feeds.yaml` | MTA subway line to API endpoint mappings |
| `Arbitrage/config.py` | Arbitrage scanner settings (thresholds, intervals) |
| `Arbitrage/requirements.txt` | Python dependencies |
| `mta_time/package.json` | Node.js dependencies and scripts |

## Key Settings (Arbitrage)

```python
MIN_MATCH_CONFIDENCE = 0.6   # LLM match confidence threshold (0.0-1.0)
MONITOR_INTERVAL_SECONDS = 60 # Price check frequency
FEE_ADJUSTMENT = 1.0         # Arbitrage calculation fee factor
```

## Data Files (Arbitrage)

- `data/polymarket_all_markets.csv` - Cached Polymarket markets
- `data/kalshi_all_markets.csv` - Cached Kalshi markets
- `data/matched_markets.csv` - LLM-identified matching market pairs

## Notes for AI Assistants

1. **Separate Projects**: The two projects are independent. Changes to one should not affect the other.

2. **Environment Variables**: Never commit actual API keys or credentials. Use `.env` files which are gitignored.

3. **MTA Feed Mapper**: When working with MTA data, use the feed mapper library (`lib/mta-feed-mapper.js`) rather than hardcoding endpoints.

4. **Testing**: No formal test frameworks. Use the provided test scripts for manual verification.

5. **Documentation**: Both projects have extensive documentation:
   - MTA: `README.md`, `HARDWARE.md`, `MAPPER_USAGE.md`
   - Arbitrage: `README.md`, `GIT_SETUP.md`, `How To Guide.md`, API docs

6. **Deployment**:
   - MTA: Designed for Raspberry Pi with systemd or PM2
   - Arbitrage: Designed for scheduled runs (cron, Task Scheduler)

7. **No Formal Build Process**: Both projects run directly from source without compilation.
