"""
New York Times Article Search API client.
"""
import requests
from datetime import datetime, timedelta
from typing import List, Dict, Any
import sys
sys.path.append('..')
from base_client import ContentClient


class NYTClient(ContentClient):
    """New York Times Article Search API client."""

    BASE_URL = "https://api.nytimes.com/svc/search/v2/articlesearch.json"

    def __init__(self, api_key: str):
        self.api_key = api_key

    def fetch_content(self, keywords: List[str], lookback_hours: int = 24) -> List[Dict[str, Any]]:
        """Fetches articles matching keywords from NYT."""
        # Build query from keywords (API has query length limits)
        query = " OR ".join(keywords[:5])

        begin_date = (datetime.now() - timedelta(hours=lookback_hours)).strftime("%Y%m%d")

        params = {
            "q": query,
            "begin_date": begin_date,
            "sort": "newest",
            "api-key": self.api_key
        }

        try:
            print(f"  Fetching NYT articles for: {query[:50]}...")
            response = requests.get(self.BASE_URL, params=params)
            response.raise_for_status()
            data = response.json()
            docs = data.get("response", {}).get("docs", [])
            print(f"  Found {len(docs)} NYT articles")
            return docs
        except requests.exceptions.HTTPError as e:
            print(f"  NYT API error: {e}")
            return []
        except Exception as e:
            print(f"  Error fetching NYT articles: {e}")
            return []

    def normalize_data(self, raw_data: Any) -> Dict[str, Any]:
        """Normalize NYT article to standard format."""
        # Extract author from byline
        byline = raw_data.get('byline', {})
        author = 'Unknown'
        if isinstance(byline, dict):
            author = byline.get('original', 'Unknown')
        elif isinstance(byline, str):
            author = byline

        # Extract headline
        headline = raw_data.get('headline', {})
        title = 'Unknown'
        if isinstance(headline, dict):
            title = headline.get('main', 'Unknown')
        elif isinstance(headline, str):
            title = headline

        return {
            'title': title,
            'url': raw_data.get('web_url', ''),
            'source': 'nyt',
            'author': author,
            'published_at': raw_data.get('pub_date', ''),
            'summary': raw_data.get('abstract', ''),
            'content': raw_data.get('lead_paragraph', ''),
            'source_id': raw_data.get('_id', ''),
            'fetched_at': datetime.now().isoformat()
        }
