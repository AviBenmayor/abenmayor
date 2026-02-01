import requests
from typing import List, Dict, Any
from base_client import MarketClient

class KalshiClient(MarketClient):
    def fetch_markets(self, max_hours_until_close: int = 24, min_volume: int = 1000, min_liquidity: int = 500) -> List[Dict[str, Any]]:
        # Using the public elections endpoint
        url = "https://api.elections.kalshi.com/trade-api/v2/markets"
        
        import datetime
        import pytz
        
        # Calculate max close time (current time + max_hours)
        now = datetime.datetime.now(pytz.utc)
        max_close_time = now + datetime.timedelta(hours=max_hours_until_close)
        max_close_ts = int(max_close_time.timestamp())
        
        params = {
            "limit": 100,
            "status": "open",
            "max_close_ts": max_close_ts  # Filter for markets closing within window
        }
        try:
            response = requests.get(url, params=params)
            response.raise_for_status()
            data = response.json()
            if 'markets' in data:
                active_markets = []
                
                for m in data['markets']:
                    # Filter out markets with low volume/liquidity
                    volume = m.get('volume', 0)
                    liquidity = m.get('liquidity', 0)
                    
                    if volume < min_volume and liquidity < min_liquidity:
                        continue
                        
                    active_markets.append(m)
                    
                return active_markets
            else:
                print(f"Unexpected Kalshi API response format: {data.keys()}")
                return []
        except Exception as e:
            print(f"Error fetching Kalshi markets: {e}")
            return []

    def normalize_data(self, raw_data: Any) -> Dict[str, Any]:
        # Kalshi market structure usually has 'title', 'yes_bid', 'yes_ask', etc.
        # We need to extract Yes/No prices.
        # Kalshi usually quotes in cents (1-99). We need to convert to 0.01-0.99.
        
        # Checking for 'yes_ask' (buy yes) and 'no_ask' (buy no).
        # If 'no_ask' is missing, it might be 100 - yes_bid? 
        # But for arbitrage we want the ASK price (cost to buy).
        
        yes_price = raw_data.get('yes_ask', 0) / 100.0
        no_price = raw_data.get('no_ask', 0) / 100.0
        
        # Extract expiry date
        expiry_date = raw_data.get('close_time', '')
        
        # Extract volume data
        # Kalshi provides 'volume' (total) and 'open_interest'
        volume = raw_data.get('volume', 0)
        open_interest = raw_data.get('open_interest', 0)
        
        # For yes/no specific volumes, we'll use total volume for both
        # since Kalshi doesn't provide separate yes/no volumes
        yes_volume = volume
        no_volume = volume
        
        return {
            'title': raw_data.get('title', 'Unknown Market'),
            'yes_price': yes_price,
            'no_price': no_price,
            'yes_volume': yes_volume,
            'no_volume': no_volume,
            'expiry_date': expiry_date,
            'platform': 'Kalshi',
            'id': raw_data.get('ticker'),
            'url': f"https://kalshi.com/markets/{raw_data.get('ticker')}",
            'category': raw_data.get('category', 'Unknown'),
            'event_ticker': raw_data.get('event_ticker', ''),
            'raw': raw_data
        }
    
    def fetch_market_by_ticker(self, ticker: str) -> Dict[str, Any]:
        """
        Fetch a specific market by its ticker.
        
        Args:
            ticker: The market ticker
        
        Returns:
            Normalized market data or None if not found
        """
        url = "https://api.elections.kalshi.com/trade-api/v2/markets"
        params = {
            "tickers": ticker,
            "limit": 1
        }
        
        try:
            response = requests.get(url, params=params)
            response.raise_for_status()
            data = response.json()
            
            if 'markets' in data and len(data['markets']) > 0:
                return self.normalize_data(data['markets'][0])
            else:
                print(f"Market {ticker} not found")
                return None
        
        except Exception as e:
            print(f"Error fetching Kalshi market {ticker}: {e}")
            return None
