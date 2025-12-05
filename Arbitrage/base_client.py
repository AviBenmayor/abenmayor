from abc import ABC, abstractmethod
from typing import List, Dict, Any

class MarketClient(ABC):
    """Abstract base class for market clients."""

    @abstractmethod
    def fetch_markets(self) -> List[Dict[str, Any]]:
        """Fetches active binary markets from the platform."""
        pass

    @abstractmethod
    def normalize_data(self, raw_data: Any) -> Dict[str, Any]:
        """Normalizes market data into a standard format:
        {
            'title': str,
            'yes_price': float,
            'no_price': float,
            'platform': str,
            'id': str,
            'url': str
        }
        """
        pass
