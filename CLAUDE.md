# CLAUDE.md - AI Assistant Guidelines

This document provides context for AI assistants working with this repository.

## Repository Overview

This is a personal projects repository containing two independent applications:

1. **MTA Train Time Display** (`mta_time/`) - Real-time NYC subway arrival display for Graham Avenue L train station
2. **Arbitrage Scanner** (`Arbitrage/`) - Prediction market arbitrage detection system for Polymarket and Kalshi

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
