"""
Abstract base class for content source clients.
"""
from abc import ABC, abstractmethod
from typing import List, Dict, Any


class ContentClient(ABC):
    """Abstract base class for content source clients."""

    @abstractmethod
    def fetch_content(self, keywords: List[str], lookback_hours: int = 24) -> List[Dict[str, Any]]:
        """
        Fetches content from the source.

        Args:
            keywords: Topic-related keywords to search for
            lookback_hours: How far back to search

        Returns:
            List of raw content items from the source
        """
        pass

    @abstractmethod
    def normalize_data(self, raw_data: Any) -> Dict[str, Any]:
        """
        Normalizes content into a standard format.

        Returns dict with:
            - title: str
            - url: str
            - source: str ('nyt', 'rss', etc.)
            - author: str
            - published_at: str (ISO format)
            - summary: str
            - content: str (full text if available)
            - source_id: str (unique ID from source)
            - fetched_at: str (ISO format)
        """
        pass
