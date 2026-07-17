import os
from pathlib import Path
from dotenv import load_dotenv

load_dotenv()

BASE_DIR = Path(__file__).parent

OPENAI_API_KEY = os.getenv("OPENAI_API_KEY")
OPENAI_MODEL = os.getenv("OPENAI_MODEL", "gpt-4o")

NOTION_API_KEY = os.getenv("NOTION_API_KEY")
NOTION_TASKS_DB_ID = os.getenv("NOTION_TASKS_DB_ID")

SMTP_SERVER = os.getenv("SMTP_SERVER", "smtp.gmail.com")
SMTP_PORT = int(os.getenv("SMTP_PORT", "587"))
SENDER_EMAIL = os.getenv("SENDER_EMAIL")
SENDER_PASSWORD = os.getenv("SENDER_PASSWORD")
RECIPIENT_EMAIL = os.getenv("RECIPIENT_EMAIL")

CONSULTING_CONTEXT = """
You are supporting Avi Benmayor, a fractional GTM Engineering consultant.
GTM Engineering = building technical infrastructure for sales, marketing, and revenue operations.
Target clients: B2B SaaS startups (Seed–Series B) needing their first GTM stack.
Core services: CRM setup, outbound tooling, RevOps automation, sales-to-marketing handoffs, PLG infrastructure.
Avi's differentiator: combines deep technical skills with GTM strategy — rare in the market.
"""
