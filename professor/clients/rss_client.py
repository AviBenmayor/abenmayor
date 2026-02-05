"""
RSS feed client for curated content sources.
"""
import feedparser
from datetime import datetime, timedelta
from typing import List, Dict, Any
import sys
sys.path.append('..')
from base_client import ContentClient


class RSSClient(ContentClient):
    """RSS feed client for curated content sources."""

    # GTM Engineering / Startup / Sales Tech relevant feeds
    DEFAULT_FEEDS = [
        "https://news.ycombinator.com/rss",
        "https://review.firstround.com/feed.xml",
        "https://a16z.com/feed/",
        "https://www.saastr.com/feed/",
        "https://tomtunguz.com/feed/",
        "https://www.lennysnewsletter.com/feed",
        "https://www.saasgrowthguide.com/rss",
    ]

    def __init__(self, feeds: List[str] = None):
        self.feeds = feeds or self.DEFAULT_FEEDS

    def fetch_content(self, keywords: List[str], lookback_hours: int = 24) -> List[Dict[str, Any]]:
        """Fetches articles from RSS feeds."""
        all_articles = []
        cutoff_time = datetime.now() - timedelta(hours=lookback_hours)

        for feed_url in self.feeds:
            try:
                print(f"  Fetching RSS: {feed_url}")
                feed = feedparser.parse(feed_url)

                for entry in feed.entries[:20]:  # Limit per feed
                    # Check if article is recent enough
                    if hasattr(entry, 'published_parsed') and entry.published_parsed:
                        try:
                            pub_time = datetime(*entry.published_parsed[:6])
                            if pub_time < cutoff_time:
                                continue
                        except (TypeError, ValueError):
                            pass  # If we can't parse date, include the article

                    all_articles.append(entry)
            except Exception as e:
                print(f"  Error fetching RSS feed {feed_url}: {e}")

        return all_articles

    def normalize_data(self, raw_data: Any) -> Dict[str, Any]:
        """Normalize RSS entry to standard format."""
        published_at = ''
        if hasattr(raw_data, 'published'):
            published_at = raw_data.published
        elif hasattr(raw_data, 'updated'):
            published_at = raw_data.updated

        # Extract content
        content = ''
        if hasattr(raw_data, 'content') and raw_data.content:
            content = raw_data.content[0].get('value', '')
        elif hasattr(raw_data, 'summary'):
            content = raw_data.summary

        return {
            'title': getattr(raw_data, 'title', 'Unknown'),
            'url': getattr(raw_data, 'link', ''),
            'source': 'rss',
            'author': getattr(raw_data, 'author', 'Unknown'),
            'published_at': published_at,
            'summary': getattr(raw_data, 'summary', '')[:500] if hasattr(raw_data, 'summary') else '',
            'content': content[:1000] if content else '',
            'source_id': getattr(raw_data, 'id', getattr(raw_data, 'link', '')),
            'fetched_at': datetime.now().isoformat()
        }
