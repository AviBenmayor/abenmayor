from abc import ABC, abstractmethod
from typing import List, Dict, Any

class MarketClient(ABC):
    """Abstract base class for market clients."""

    @abstractmethod
    def fetch_markets(self, max_hours_until_close: int = 24, min_volume: int = 1000, min_liquidity: int = 500) -> List[Dict[str, Any]]:
        """
        Fetches active binary markets from the platform.
        
        Args:
            max_hours_until_close: Include markets closing within this many hours
            min_volume: Minimum trading volume to include
            min_liquidity: Minimum liquidity to include
        """
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
