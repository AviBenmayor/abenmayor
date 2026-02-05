"""
Professor - Personal Knowledge Building System
Main orchestration module.
"""
import os
import sys
from datetime import datetime
from dotenv import load_dotenv

# Add project root to path
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

load_dotenv()


def run_daily_pipeline():
    """Execute the complete daily pipeline."""
    import config
    from pipeline.content_fetcher import ContentFetcher
    from pipeline.relevance_scorer import RelevanceScorer
    from pipeline.content_processor import ContentProcessor
    from clients.notion_client import NotionClient
    from email_sender import EmailSender

    print("=" * 60)
    print(f"PROFESSOR DAILY RUN - {datetime.now()}")
    print(f"Topic: {config.CURRENT_TOPIC}")
    print("=" * 60)

    # Step 1: Fetch content from all sources
    print("\n[1/5] Fetching content...")
    fetcher = ContentFetcher()
    raw_articles = fetcher.fetch_all()

    if not raw_articles:
        print("No articles fetched. Exiting.")
        return

    # Step 2: Process and deduplicate
    print("\n[2/5] Processing content...")
    processor = ContentProcessor()
    unique_articles = processor.deduplicate(raw_articles)

    if not unique_articles:
        print("No new articles after deduplication. Exiting.")
        return

    # Step 3: Score relevance
    print("\n[3/5] Scoring relevance...")
    scorer = RelevanceScorer()
    scored_articles = scorer.score_articles(unique_articles)
    relevant_articles = processor.filter_by_relevance(scored_articles)

    if not relevant_articles:
        print("No articles passed relevance threshold. Exiting.")
        return

    # Step 4: Save to Notion
    print("\n[4/5] Saving to Notion...")
    if config.NOTION_API_KEY and config.NOTION_DATABASE_ID:
        notion = NotionClient()
        notion.add_articles(relevant_articles)
    else:
        print("Notion not configured. Skipping.")

    # Step 5: Send email digest
    print("\n[5/5] Sending email digest...")
    emailer = EmailSender()
    top_articles = processor.get_top_articles(relevant_articles)
    emailer.send_digest(top_articles)

    # Persist to CSV
    processor.save_articles(relevant_articles)

    print("\n" + "=" * 60)
    print("DAILY RUN COMPLETE")
    print(f"  - Fetched: {len(raw_articles)} articles")
    print(f"  - Unique: {len(unique_articles)} articles")
    print(f"  - Relevant: {len(relevant_articles)} articles")
    print("=" * 60)


def fetch_only(return_articles=False):
    """Fetch content without scoring or sending.

    Args:
        return_articles: If True, return scored articles instead of just printing

    Returns:
        List of articles if return_articles=True, else None
    """
    import config
    from pipeline.content_fetcher import ContentFetcher
    from pipeline.content_processor import ContentProcessor
    from pipeline.relevance_scorer import RelevanceScorer

    print("Fetching content...")
    fetcher = ContentFetcher()
    articles = fetcher.fetch_all()

    processor = ContentProcessor()
    unique = processor.deduplicate(articles)

    # Score articles
    scorer = RelevanceScorer()
    scored = scorer.score_articles(unique)

    # Save to CSV
    processor.save_articles(scored)

    print(f"\nFetched {len(articles)} articles, {len(unique)} unique")

    if return_articles:
        return scored
    return None


def send_email_only():
    """Send digest from stored articles."""
    import config
    import csv
    from email_sender import EmailSender

    articles = []
    try:
        with open(config.ARTICLES_FILE, 'r', newline='', encoding='utf-8') as f:
            reader = csv.DictReader(f)
            for row in reader:
                try:
                    row['relevance_score'] = float(row.get('relevance_score', 0))
                except ValueError:
                    row['relevance_score'] = 0.5
                articles.append(row)
    except FileNotFoundError:
        print(f"No articles file found at {config.ARTICLES_FILE}")
        return

    # Get last 20 articles
    recent = articles[-20:] if len(articles) > 20 else articles
    emailer = EmailSender()
    emailer.send_digest(recent)


if __name__ == "__main__":
    if len(sys.argv) > 1:
        cmd = sys.argv[1].lower()
        if cmd == "run":
            run_daily_pipeline()
        elif cmd == "fetch":
            fetch_only()
        elif cmd == "email":
            send_email_only()
        else:
            print(f"Unknown command: {cmd}")
            print("Usage: python main.py [run|fetch|email]")
    else:
        print("Usage: python main.py [run|fetch|email]")
