"""
Configuration settings for Professor - Personal Knowledge Building System.
"""
import os
from pathlib import Path
from dotenv import load_dotenv

load_dotenv()

# Base directory
BASE_DIR = Path(__file__).parent

# File Paths
DATA_DIR = BASE_DIR / "data"
ARTICLES_FILE = DATA_DIR / "articles.csv"
SENT_DIGESTS_FILE = DATA_DIR / "sent_digests.csv"
DATA_DIR.mkdir(exist_ok=True)

# Topic Configuration
CURRENT_TOPIC = "GTM Engineering"
TOPIC_KEYWORDS = [
    "go-to-market", "GTM", "sales engineering", "revenue operations",
    "product-led growth", "PLG", "first GTM hire", "startup sales",
    "sales automation", "CRM", "outbound", "inbound marketing",
    "growth engineering", "sales tech", "RevOps"
]
TOPIC_DESCRIPTION = """
GTM (Go-To-Market) Engineering: The discipline of building technical
infrastructure for sales, marketing, and revenue operations. Includes
tools, techniques, automation, and strategies for startup growth.
Focus areas: tools and techniques, making impact as first GTM hire,
history and evolution of the role, biggest impact projects in the space.
"""

# Relevance Scoring (0.9+ for high-quality supplementary articles)
MIN_RELEVANCE_SCORE = 0.9

# Spaced Repetition Intervals (in days)
SPACED_REPETITION_INTERVALS = {
    1: 1,    # First review: 1 day
    2: 3,    # Second review: 3 days
    3: 7,    # Third review: 7 days
    4: 14,   # Fourth review: 14 days
    5: 30,   # Fifth+ review: 30 days
}
FAILED_RECALL_RESET_DAYS = 1  # Reset to 1 day on failed recall

# Content Settings
MAX_ARTICLES_PER_SOURCE = 50
MAX_ARTICLES_IN_DIGEST = 5  # Reduced - articles are supplementary now
LOOKBACK_HOURS = 24

# API Keys (from environment)
NYT_API_KEY = os.getenv("NYT_API_KEY")
NOTION_API_KEY = os.getenv("NOTION_API_KEY")
NOTION_DATABASE_ID = os.getenv("NOTION_DATABASE_ID")
OPENAI_API_KEY = os.getenv("OPENAI_API_KEY")

# Email Configuration
SMTP_SERVER = os.getenv("SMTP_SERVER", "smtp.gmail.com")
SMTP_PORT = int(os.getenv("SMTP_PORT", "587"))
SENDER_EMAIL = os.getenv("SENDER_EMAIL")
SENDER_PASSWORD = os.getenv("SENDER_PASSWORD")
RECIPIENT_EMAIL = os.getenv("RECIPIENT_EMAIL")

# Scheduling
DAILY_RUN_HOUR = 7  # 7 AM local time
DAILY_RUN_MINUTE = 0
