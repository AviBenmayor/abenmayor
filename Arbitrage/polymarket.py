import requests
from typing import List, Dict, Any
from base_client import MarketClient

class PolymarketClient(MarketClient):
    def fetch_markets(self) -> List[Dict[str, Any]]:
        # Using the correct Gamma API endpoint
        url = "https://gamma-api.polymarket.com/markets"
        params = {
            "closed": "false",
            "active": "true",
            "limit": 100
        }
        try:
            response = requests.get(url, params=params)
            response.raise_for_status()
            data = response.json()
            
            # The Gamma API returns a list of markets directly
            if not isinstance(data, list):
                print(f"Unexpected Polymarket API response format: {type(data)}")
                return []
            
            # Client-side filtering for active markets
            active_markets = []
            import datetime
            import calendar
            
            now = datetime.datetime.now(datetime.timezone.utc)
            
            # Calculate end of current month
            year = now.year
            month = now.month
            last_day = calendar.monthrange(year, month)[1]
            end_of_month = datetime.datetime(year, month, last_day, 23, 59, 59, tzinfo=datetime.timezone.utc)
            
            for m in data:
                # Check 'closed' and 'active' fields
                if m.get('closed') is True or m.get('active') is not True:
                    continue
                    
                # Check 'endDateIso' - only include markets that expire AFTER end of current month
                end_date_str = m.get('endDateIso')
                if end_date_str:
                    try:
                        end_date = datetime.datetime.fromisoformat(end_date_str.replace('Z', '+00:00'))
                        
                        # Ensure timezone-aware comparison
                        if end_date.tzinfo is None:
                            end_date = end_date.replace(tzinfo=datetime.timezone.utc)
                        
                        # Skip markets that expire before end of current month
                        if end_date <= end_of_month:
                            continue
                    except ValueError:
                        pass
                
                # Filter out markets with no volume/activity
                # Polymarket provides: volume, volumeNum, liquidity, liquidityNum
                volume = m.get('volumeNum', 0)
                liquidity = m.get('liquidityNum', 0)
                
                # Skip if all volume indicators are 0
                if volume == 0 and liquidity == 0:
                    continue
                
                active_markets.append(m)
                
            return active_markets
        except Exception as e:
            print(f"Error fetching Polymarket markets: {e}")
            return []

    def normalize_data(self, raw_data: Any) -> Dict[str, Any]:
        # Polymarket Gamma API structure
        title = raw_data.get('question', 'Unknown Market')
        
        # Extract expiry date
        expiry_date = raw_data.get('endDateIso', '')
        
        # Extract volume data
        volume = raw_data.get('volumeNum', 0)
        
        # For yes/no specific volumes, use total volume for both
        # Polymarket doesn't provide separate yes/no volumes in the markets endpoint
        yes_volume = volume
        no_volume = volume
        
        # NOTE: Prices are NOT available from the gamma-api /markets endpoint
        # According to the orderbook schema, prices require calling GET /book 
        # with token_id for each market, which isn't practical for bulk scanning
        # For now, prices remain as 0.0 placeholders
        yes_price = 0.0
        no_price = 0.0
        
        return {
            'title': title,
            'yes_price': yes_price,
            'no_price': no_price,
            'yes_volume': yes_volume,
            'no_volume': no_volume,
            'expiry_date': expiry_date,
            'platform': 'Polymarket',
            'id': raw_data.get('conditionId') or raw_data.get('slug'),
            'url': f"https://polymarket.com/event/{raw_data.get('slug', '')}",
            'raw': raw_data
        }
    
    def fetch_market_by_id(self, market_id: str) -> Dict[str, Any]:
        """
        Fetch a specific market by its condition ID.
        
        Args:
            market_id: The conditionId of the market
        
        Returns:
            Normalized market data or None if not found
        """
        # The Gamma API doesn't have a direct ID lookup endpoint
        # We need to fetch and filter (or use a different approach)
        # For now, we'll return None and note this limitation
        # TODO: Implement orderbook-based price fetching
        print(f"Warning: fetch_market_by_id not fully implemented for Polymarket")
        print(f"Prices for {market_id} will be 0.0")
        return None
