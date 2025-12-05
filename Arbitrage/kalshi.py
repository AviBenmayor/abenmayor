import requests
from typing import List, Dict, Any
from base_client import MarketClient

class KalshiClient(MarketClient):
    def fetch_markets(self) -> List[Dict[str, Any]]:
        # Using the public elections endpoint
        url = "https://api.elections.kalshi.com/trade-api/v2/markets"
        
        # Calculate end of current month timestamp for filtering
        import datetime
        import calendar
        import pytz
        
        eastern_timezone = pytz.timezone('America/New_York')
        now = datetime.datetime.now(eastern_timezone)
        
        year = now.year
        month = now.month
        last_day = calendar.monthrange(year, month)[1]
        end_of_month = datetime.datetime(year, month, last_day, 23, 59, 59, tzinfo=eastern_timezone)
        
        # Convert to Unix timestamp for API
        min_close_ts = int(end_of_month.timestamp())
        
        params = {
            "limit": 100,
            "status": "open",  # Per documentation: use 'open' for filtering (API returns 'active')
            "min_close_ts": min_close_ts  # Only get markets that close after end of current month
        }
        try:
            response = requests.get(url, params=params)
            response.raise_for_status()
            data = response.json()
            if 'markets' in data:
                # Client-side filtering for volume/liquidity
                active_markets = []
                
                for m in data['markets']:
                    # Filter out markets with no volume/liquidity
                    # Kalshi provides: volume, open_interest, liquidity
                    volume = m.get('volume', 0)
                    open_interest = m.get('open_interest', 0)
                    liquidity = m.get('liquidity', 0)
                    
                    # Skip if all activity indicators are 0
                    if volume == 0 and open_interest == 0 and liquidity == 0:
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
