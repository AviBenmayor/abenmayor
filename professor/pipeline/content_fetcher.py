"""
Orchestrates fetching content from all configured sources.
"""
from typing import List, Dict, Any
import sys
sys.path.append('..')
import config
from clients.rss_client import RSSClient
from clients.nyt_client import NYTClient


class ContentFetcher:
    """Orchestrates fetching content from all sources."""

    def __init__(self):
        self.clients = []

        # RSS always available (no API key needed)
        self.clients.append(RSSClient())
        print("RSS client initialized")

        # Initialize NYT if API key available
        if config.NYT_API_KEY:
            self.clients.append(NYTClient(config.NYT_API_KEY))
            print("NYT client initialized")
        else:
            print("NYT API key not found - skipping NYT client")

    def fetch_all(self) -> List[Dict[str, Any]]:
        """Fetch content from all configured sources."""
        all_content = []

        for client in self.clients:
            client_name = client.__class__.__name__
            print(f"\nFetching from {client_name}...")

            try:
                raw_content = client.fetch_content(
                    keywords=config.TOPIC_KEYWORDS,
                    lookback_hours=config.LOOKBACK_HOURS
                )

                # Normalize each item
                for item in raw_content[:config.MAX_ARTICLES_PER_SOURCE]:
                    try:
                        normalized = client.normalize_data(item)
                        if normalized.get('title') and normalized.get('url'):
                            all_content.append(normalized)
                    except Exception as e:
                        print(f"  Error normalizing item: {e}")

                print(f"  Processed {len(raw_content)} items from {client_name}")
            except Exception as e:
                print(f"  Error with {client_name}: {e}")

        print(f"\nTotal content fetched: {len(all_content)}")
        return all_content
