"""
Configuration settings for the Arbitrage Scanner.
"""
import os
from pathlib import Path

# Base directory
BASE_DIR = Path(__file__).parent

# Market Discovery Settings
DISCOVERY_SCHEDULE = "every_30_minutes"  # User requested 30 min interval
DISCOVERY_INTERVAL_MINUTES = 30
MIN_MATCH_CONFIDENCE = 0.6  # Minimum confidence score for LLM matches (0.0 to 1.0)

# Live Market Filtering
MAX_HOURS_UNTIL_CLOSE = 24  # Focus on events ending within 24 hours
MIN_MARKET_VOLUME = 1000    # Minimum volume to consider
MIN_MARKET_LIQUIDITY = 500  # Minimum liquidity to consider

# Price Monitor Settings
MONITOR_INTERVAL_SECONDS = 5  # streaming-like polling for now, until websocket implemented
PRICE_FETCH_BATCH_SIZE = 10  # Number of markets to fetch at once

# File Paths
DATA_DIR = BASE_DIR / "data"
MATCHED_MARKETS_FILE = DATA_DIR / "matched_markets.csv"
POLYMARKET_ALL_FILE = DATA_DIR / "polymarket_all_markets.csv"
KALSHI_ALL_FILE = DATA_DIR / "kalshi_all_markets.csv"

# Ensure data directory exists
DATA_DIR.mkdir(exist_ok=True)

# API Settings (from environment)
OPENAI_API_KEY = os.getenv("OPENAI_API_KEY")

# Email/Notification Settings
SMTP_SERVER = os.getenv("SMTP_SERVER", "smtp.gmail.com")
SMTP_PORT = int(os.getenv("SMTP_PORT", "587"))
SENDER_EMAIL = os.getenv("SENDER_EMAIL")
SENDER_PASSWORD = os.getenv("SENDER_PASSWORD")
RECIPIENT_EMAIL = os.getenv("RECIPIENT_EMAIL")

# Arbitrage Settings
FEE_ADJUSTMENT = 1.0  # Fee adjustment factor for arbitrage calculation
