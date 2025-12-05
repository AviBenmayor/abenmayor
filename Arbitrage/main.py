from polymarket import PolymarketClient
from kalshi import KalshiClient
from market_matcher import MarketMatcher
from arbitrage_engine import ArbitrageEngine
from notifier import Notifier
from dotenv import load_dotenv
import os
import csv
from datetime import datetime

def main():
    load_dotenv()
    print("Starting Arbitrage Scanner...")
    
    # Initialize components with default fee adjustment
    fee_adj = 1.0
        
    poly_client = PolymarketClient()
    kalshi_client = KalshiClient()
    matcher = MarketMatcher()
    engine = ArbitrageEngine(fee_adjustment=fee_adj)
    notifier = Notifier()

    # 1. Fetch Markets
    print("Fetching markets from Polymarket...")
    poly_raw = poly_client.fetch_markets()
    poly_markets = [poly_client.normalize_data(m) for m in poly_raw]
    print(f"Fetched {len(poly_markets)} markets from Polymarket.")
    
    # Save Polymarket markets to CSV
    save_markets_to_csv(poly_markets, "polymarket_markets.csv")

    print("Fetching markets from Kalshi...")
    kalshi_raw = kalshi_client.fetch_markets()
    kalshi_markets = [kalshi_client.normalize_data(m) for m in kalshi_raw]
    print(f"Fetched {len(kalshi_markets)} markets from Kalshi.")
    
    # Save Kalshi markets to CSV
    save_markets_to_csv(kalshi_markets, "kalshi_markets.csv")

    # 2. Match Markets
    print("Matching markets (this may take a moment)...")
    matched_pairs = matcher.match_markets(poly_markets, kalshi_markets)
    print(f"Found {len(matched_pairs)} matched pairs.")

    # 3. Find Arbitrage
    print("Checking for arbitrage opportunities...")
    opportunities = engine.find_opportunities(matched_pairs)

    # 4. Notify
    if opportunities:
        notifier.send_notification(opportunities)
    else:
        print("No arbitrage opportunities found at this time.")

def save_markets_to_csv(markets, filename):
    """Save markets to a CSV file for inspection."""
    if not markets:
        print(f"No markets to save to {filename}")
        return
    
    timestamp = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    
    with open(filename, 'w', newline='', encoding='utf-8') as csvfile:
        fieldnames = ['id', 'title', 'platform', 'expiry_date', 'yes_price', 'no_price', 'yes_volume', 'no_volume']
        writer = csv.DictWriter(csvfile, fieldnames=fieldnames)
        
        writer.writeheader()
        for market in markets:
            writer.writerow({
                'id': market.get('id', ''),
                'title': market.get('title', ''),
                'platform': market.get('platform', ''),
                'expiry_date': market.get('expiry_date', ''),
                'yes_price': market.get('yes_price', ''),
                'no_price': market.get('no_price', ''),
                'yes_volume': market.get('yes_volume', ''),
                'no_volume': market.get('no_volume', '')
            })
    
    print(f"Saved {len(markets)} markets to {filename} (fetched at {timestamp})")

if __name__ == "__main__":
    main()
