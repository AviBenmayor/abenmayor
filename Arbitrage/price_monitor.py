"""
Price Monitor Module

This module continuously monitors prices for matched markets,
calculates arbitrage opportunities, and sends notifications.
"""
import csv
import time
from typing import List, Dict, Any
from datetime import datetime
from polymarket import PolymarketClient
from kalshi import KalshiClient
from arbitrage_engine import ArbitrageEngine
from notifier import Notifier
import config


def load_matched_markets() -> List[Dict]:
    """
    Load matched markets from CSV file.
    
    Returns:
        List of matched market dictionaries
    """
    matched_markets = []
    
    try:
        with open(config.MATCHED_MARKETS_FILE, 'r', encoding='utf-8') as csvfile:
            reader = csv.DictReader(csvfile)
            for row in reader:
                matched_markets.append(row)
        
        print(f"Loaded {len(matched_markets)} matched market pairs")
        return matched_markets
    
    except FileNotFoundError:
        print(f"Error: {config.MATCHED_MARKETS_FILE} not found")
        print("Please run market discovery first: python market_discovery.py")
        return []


def fetch_current_prices(matched_markets: List[Dict]) -> List[Dict]:
    """
    Fetch current prices for matched markets.
    
    Args:
        matched_markets: List of matched market pairs
    
    Returns:
        List of matched pairs with current price data
    """
    poly_client = PolymarketClient()
    kalshi_client = KalshiClient()
    
    pairs_with_prices = []
    
    for pair in matched_markets:
        try:
            # Fetch Polymarket market
            poly_id = pair['id_polymarket']
            poly_market = poly_client.fetch_market_by_id(poly_id)
            
            # Fetch Kalshi market
            kalshi_ticker = pair['id_kalshi']
            kalshi_market = kalshi_client.fetch_market_by_ticker(kalshi_ticker)
            
            if poly_market and kalshi_market:
                pairs_with_prices.append({
                    'market_a': poly_market,
                    'market_b': kalshi_market,
                    'confidence': float(pair.get('confidence', 0.0))
                })
        
        except Exception as e:
            print(f"Error fetching prices for {pair['title_polymarket']}: {e}")
            continue
    
    print(f"Fetched prices for {len(pairs_with_prices)} market pairs")
    return pairs_with_prices


def calculate_arbitrage(pairs_with_prices: List[Dict]) -> List[Dict]:
    """
    Calculate arbitrage opportunities from matched pairs with prices.
    
    Args:
        pairs_with_prices: List of matched pairs with current prices
    
    Returns:
        List of arbitrage opportunities
    """
    engine = ArbitrageEngine(fee_adjustment=config.FEE_ADJUSTMENT)
    opportunities = engine.find_opportunities(pairs_with_prices)
    
    if opportunities:
        print(f"Found {len(opportunities)} arbitrage opportunities!")
    else:
        print("No arbitrage opportunities found")
    
    return opportunities


def monitor_loop():
    """
    Continuous monitoring loop that checks for arbitrage opportunities.
    """
    print("=" * 60)
    print("PRICE MONITOR MODULE")
    print("=" * 60)
    
    # Load matched markets once
    matched_markets = load_matched_markets()
    
    if not matched_markets:
        print("No matched markets to monitor. Exiting.")
        return
    
    notifier = Notifier()
    iteration = 0
    
    print(f"Monitoring {len(matched_markets)} matched market pairs")
    print(f"Check interval: {config.MONITOR_INTERVAL_SECONDS} seconds")
    print("Press Ctrl+C to stop")
    print("=" * 60)
    
    try:
        while True:
            iteration += 1
            timestamp = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
            print(f"\n[{timestamp}] Iteration {iteration}")
            
            # Fetch current prices
            pairs_with_prices = fetch_current_prices(matched_markets)
            
            # Calculate arbitrage
            opportunities = calculate_arbitrage(pairs_with_prices)
            
            # Send notifications if opportunities found
            if opportunities:
                notifier.send_notification(opportunities)
            
            # Wait before next iteration
            print(f"Waiting {config.MONITOR_INTERVAL_SECONDS} seconds...")
            time.sleep(config.MONITOR_INTERVAL_SECONDS)
    
    except KeyboardInterrupt:
        print("\n\nMonitoring stopped by user")
        print("=" * 60)


if __name__ == "__main__":
    monitor_loop()
