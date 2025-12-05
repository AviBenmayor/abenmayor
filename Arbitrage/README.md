# Arbitrage Scanner

A modular arbitrage detection system for prediction markets on Polymarket and Kalshi.

## Architecture

The system is split into two modules:

1. **Market Discovery** (`market_discovery.py`): Weekly scraping and LLM-based matching
2. **Price Monitor** (`price_monitor.py`): Continuous price monitoring of matched markets

## Quick Start

### 1. Install Dependencies

```bash
pip install -r requirements.txt
```

### 2. Set Environment Variables

Create a `.env` file or set environment variables:

```bash
OPENAI_API_KEY=your_openai_api_key
SENDER_EMAIL=your_email@gmail.com
SENDER_PASSWORD=your_app_password
RECIPIENT_EMAIL=recipient@email.com
```

### 3. Run Market Discovery (Weekly)

```bash
python cli.py discover
```

This will:
- Scrape all active markets from Polymarket and Kalshi
- Save metadata to `data/polymarket_all_markets.csv` and `data/kalshi_all_markets.csv`
- Run LLM matching to find identical markets
- Save high-confidence matches (≥0.8) to `data/matched_markets.csv`

### 4. Run Price Monitor (Continuous)

```bash
python cli.py monitor
```

This will:
- Load matched markets from CSV
- Fetch current prices every 60 seconds
- Calculate arbitrage opportunities
- Send email notifications when found

### 5. Run Both

```bash
python cli.py run-all
```

## Configuration

Edit `config.py` to customize:

```python
# Confidence threshold for LLM matches
MIN_MATCH_CONFIDENCE = 0.8  # 0.0 to 1.0

# Price monitoring interval
MONITOR_INTERVAL_SECONDS = 60  # seconds

# Fee adjustment for arbitrage calculation
FEE_ADJUSTMENT = 1.0
```

## Data Files

All data is stored in the `data/` directory:

- `polymarket_all_markets.csv`: All Polymarket markets (id, title, expiry_date)
- `kalshi_all_markets.csv`: All Kalshi markets (id, title, expiry_date)
- `matched_markets.csv`: High-confidence matched pairs with confidence scores

## CLI Commands

```bash
# Market discovery
python cli.py discover

# Price monitoring
python cli.py monitor

# Both (discovery then monitoring)
python cli.py run-all

# Or run modules directly
python market_discovery.py
python price_monitor.py
```

## How It Works

### Market Discovery

1. **Scraping**: Fetches all active markets from both platforms
2. **Pre-filtering**: Uses lexical overlap to reduce LLM token usage
3. **LLM Matching**: Uses GPT-5-mini to identify identical markets with confidence scores
4. **Filtering**: Only saves matches with confidence ≥ 0.8

### Price Monitoring

1. **Loading**: Reads matched markets from CSV
2. **Price Fetching**: Gets current prices for matched markets only
3. **Arbitrage Calculation**: Checks if `0.95 - (Yes_A + No_B) > 0`
4. **Notification**: Sends email when opportunities found

## Efficiency Benefits

- **Before**: Fetched 200+ markets continuously, ran LLM matching every time
- **After**: LLM runs weekly, price monitoring fetches only ~10-20 matched markets

## Legacy System

The old `main.py` still works but is less efficient. Use the new modular system for production.

## Scheduling

### Windows (Task Scheduler)
Run market discovery weekly:
```powershell
schtasks /create /tn "Market Discovery" /tr "python C:\path\to\cli.py discover" /sc weekly /d SUN /st 00:00
```

### Linux/Mac (cron)
```bash
# Run discovery every Sunday at midnight
0 0 * * 0 cd /path/to/Arbitrage && python cli.py discover
```

## Troubleshooting

**No matches found**: This is normal if there are no identical markets across platforms. The system requires exact event matches.

**OPENAI_API_KEY not found**: Set the environment variable or add to `.env` file.

**Polymarket prices are 0.0**: The Gamma API doesn't provide prices directly. This is a known limitation.

## License

MIT
