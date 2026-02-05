#!/usr/bin/env python3
"""
Professor CLI - Personal Knowledge Building System

Usage:
    python cli.py run          # Run full daily pipeline (newsletter + articles)
    python cli.py learn        # Start interactive learning session with Claude
    python cli.py learn <topic># Deep dive on a specific topic
    python cli.py quiz         # Generate and send daily learning newsletter
    python cli.py fetch        # Fetch articles only (no scoring/email)
    python cli.py email        # Send article digest from stored articles
    python cli.py status       # Show current configuration status
    python cli.py help         # Show this help message
"""
import os
import sys

# Add project root to path
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from dotenv import load_dotenv
load_dotenv()


def print_usage():
    """Print usage information."""
    print(__doc__)


def show_status():
    """Show current configuration status."""
    import config

    print("\n" + "=" * 50)
    print("PROFESSOR STATUS")
    print("=" * 50)

    print(f"\nCurrent Topic: {config.CURRENT_TOPIC}")
    print(f"Keywords: {', '.join(config.TOPIC_KEYWORDS[:5])}...")

    print("\n--- API Status ---")
    print(f"NYT API:     {'Configured' if config.NYT_API_KEY else 'Not configured'}")
    print(f"Notion API:  {'Configured' if config.NOTION_API_KEY else 'Not configured'}")
    print(f"Notion DB:   {'Configured' if config.NOTION_DATABASE_ID else 'Not configured'}")
    print(f"Claude API:  {'Configured' if config.ANTHROPIC_API_KEY else 'Not configured'}")

    print("\n--- Email Status ---")
    print(f"SMTP Server: {config.SMTP_SERVER}:{config.SMTP_PORT}")
    print(f"Sender:      {'Configured' if config.SENDER_EMAIL else 'Not configured'}")
    print(f"Recipient:   {'Configured' if config.RECIPIENT_EMAIL else 'Not configured'}")

    print("\n--- Files ---")
    print(f"Articles:    {config.ARTICLES_FILE}")
    print(f"Digests:     {config.SENT_DIGESTS_FILE}")

    # Count existing articles
    try:
        with open(config.ARTICLES_FILE, 'r') as f:
            lines = sum(1 for _ in f) - 1  # Subtract header
            print(f"  -> {max(0, lines)} articles stored")
    except FileNotFoundError:
        print("  -> No articles yet")

    print("\n" + "=" * 50)


def run_learn_session(topic=None):
    """Start an interactive learning session."""
    import config
    if not config.ANTHROPIC_API_KEY:
        print("Error: ANTHROPIC_API_KEY required for learning sessions")
        print("Add your API key to .env file")
        sys.exit(1)

    from learning_session import LearningSession, deep_dive

    if topic:
        # Deep dive on specific topic
        deep_dive(topic)
    else:
        # Full learning session
        session = LearningSession()
        session.start_session()


def run_quiz():
    """Generate and send daily learning newsletter."""
    from newsletter_generator import NewsletterGenerator
    from email_sender import EmailSender

    generator = NewsletterGenerator()

    # Optionally fetch high-relevance articles
    try:
        from main import fetch_only
        articles = fetch_only(return_articles=True)
        # Filter to only 0.9+ relevance
        import config
        articles = [a for a in articles if a.get('relevance_score', 0) >= config.MIN_RELEVANCE_SCORE]
    except Exception:
        articles = []

    newsletter = generator.generate_newsletter(articles)

    # Print to console
    print(generator.format_as_text(newsletter))

    # Send email
    sender = EmailSender()
    html = generator.format_as_html(newsletter)
    text = generator.format_as_text(newsletter)
    sender.send_learning_newsletter(newsletter, html, text)


def main():
    """Main CLI entry point."""
    if len(sys.argv) < 2:
        print_usage()
        sys.exit(1)

    command = sys.argv[1].lower()

    if command == "run":
        # New run: newsletter first, then supplementary articles
        run_quiz()

    elif command == "learn":
        # Interactive learning session
        topic = " ".join(sys.argv[2:]) if len(sys.argv) > 2 else None
        run_learn_session(topic)

    elif command == "quiz":
        # Generate and send newsletter
        run_quiz()

    elif command == "fetch":
        from main import fetch_only
        fetch_only()

    elif command == "email":
        from main import send_email_only
        send_email_only()

    elif command == "status":
        show_status()

    elif command in ["help", "-h", "--help"]:
        print_usage()

    else:
        print(f"Unknown command: {command}")
        print_usage()
        sys.exit(1)


if __name__ == "__main__":
    main()
