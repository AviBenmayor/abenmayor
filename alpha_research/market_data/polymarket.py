import requests
from typing import List, Dict, Any
from .base_client import MarketClient

class PolymarketClient(MarketClient):
    def fetch_markets(self, max_hours_until_close: int = 24, min_volume: int = 1000, min_liquidity: int = 500) -> List[Dict[str, Any]]:
        # Using the correct Gamma API endpoint
        url = "https://gamma-api.polymarket.com/markets"
        
        import datetime
        import calendar
        
        # Calculate max end date
        now = datetime.datetime.now(datetime.timezone.utc)
        max_end_date = now + datetime.timedelta(hours=max_hours_until_close)
        
        params = {
            "closed": "false",
            "active": "true",
            "limit": 500,  # Increase limit to ensuring we find live markets if server-side filtering is weak
            "offset": 0
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
            
            for m in data:
                # Check 'closed' and 'active' fields
                if m.get('closed') is True or m.get('active') is not True:
                    continue
                    
                # Check 'endDateIso'
                end_date_str = m.get('endDateIso')
                if end_date_str:
                    try:
                        end_date = datetime.datetime.fromisoformat(end_date_str.replace('Z', '+00:00'))
                        
                        # Ensure timezone-aware comparison
                        if end_date.tzinfo is None:
                            end_date = end_date.replace(tzinfo=datetime.timezone.utc)
                        
                        # Filter: Must close BEFORE max_end_date (and after now)
                        if end_date > max_end_date:
                            continue
                            
                        # Optional: Don't show already expired markets? 
                        # Arbitrage might still work if not settled, but usually we want future events
                        if end_date < now:
                            continue
                            
                    except ValueError:
                        pass
                
                # Filter out markets with low volume/activity
                # Polymarket provides: volume, volumeNum, liquidity, liquidityNum
                volume = m.get('volumeNum', 0)
                liquidity = m.get('liquidityNum', 0)
                
                if volume < min_volume and liquidity < min_liquidity:
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
        
        # Extract prices from outcomePrices
        # outcomePrices is usually a list of strings like ["0.50", "0.50"]
        # outcomes is a list of strings like ["Yes", "No"]
        # Note: The API sometimes returns these as JSON strings, so we need to parse them.
        import json
        
        outcome_prices = raw_data.get('outcomePrices', [])
        if isinstance(outcome_prices, str):
            try:
                outcome_prices = json.loads(outcome_prices)
            except json.JSONDecodeError:
                outcome_prices = []
                
        outcomes = raw_data.get('outcomes', [])
        if isinstance(outcomes, str):
            try:
                outcomes = json.loads(outcomes)
            except json.JSONDecodeError:
                outcomes = []
        
        yes_price = 0.0
        no_price = 0.0
        
        if outcome_prices and outcomes and len(outcome_prices) == len(outcomes):
            try:
                # Map outcomes to prices
                # We assume standard "Yes"/"No" binary markets for now
                for i, outcome in enumerate(outcomes):
                    price = float(outcome_prices[i])
                    if outcome == "Yes":
                        yes_price = price
                    elif outcome == "No":
                        no_price = price
            except (ValueError, TypeError):
                print(f"Error parsing prices for {title}")
        
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
            'category': raw_data.get('tags', [])[0] if raw_data.get('tags') else 'Unknown',
            'tags': raw_data.get('tags', []),
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
