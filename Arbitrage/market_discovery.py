"""
Market Discovery Module

This module handles weekly/on-demand scraping of all active markets from
Polymarket and Kalshi, runs LLM matching to find high-confidence pairs,
and saves the results for the price monitor to use.
"""
import csv
from datetime import datetime
from typing import List, Dict, Any
from polymarket import PolymarketClient
from kalshi import KalshiClient
from market_matcher import MarketMatcher
import config


def scrape_all_markets() -> tuple[List[Dict], List[Dict]]:
    """
    Scrape all active markets from both Polymarket and Kalshi.
    
    Returns:
        tuple: (polymarket_markets, kalshi_markets)
    """
    print("Scraping all markets from Polymarket...")
    poly_client = PolymarketClient()
    poly_raw = poly_client.fetch_markets()
    poly_markets = [poly_client.normalize_data(m) for m in poly_raw]
    print(f"Found {len(poly_markets)} markets from Polymarket")
    
    print("Scraping all markets from Kalshi...")
    kalshi_client = KalshiClient()
    kalshi_raw = kalshi_client.fetch_markets()
    kalshi_markets = [kalshi_client.normalize_data(m) for m in kalshi_raw]
    print(f"Found {len(kalshi_markets)} markets from Kalshi")
    
    return poly_markets, kalshi_markets


def save_market_metadata(markets: List[Dict], filepath: str, platform: str):
    """
    Save market metadata (id, title, expiry_date) to CSV.
    
    Args:
        markets: List of normalized market dictionaries
        filepath: Path to save CSV file
        platform: Platform name (for logging)
    """
    if not markets:
        print(f"No {platform} markets to save")
        return
    
    scraped_at = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    
    with open(filepath, 'w', newline='', encoding='utf-8') as csvfile:
        fieldnames = ['id', 'title', 'expiry_date', 'scraped_at']
        writer = csv.DictWriter(csvfile, fieldnames=fieldnames)
        
        writer.writeheader()
        for market in markets:
            writer.writerow({
                'id': market.get('id', ''),
                'title': market.get('title', ''),
                'expiry_date': market.get('expiry_date', ''),
                'scraped_at': scraped_at
            })
    
    print(f"Saved {len(markets)} {platform} markets to {filepath}")


def run_matching(poly_markets: List[Dict], kalshi_markets: List[Dict]) -> List[Dict]:
    """
    Run LLM matching to find high-confidence market pairs.
    
    Args:
        poly_markets: List of Polymarket markets
        kalshi_markets: List of Kalshi markets
    
    Returns:
        List of matched pairs with confidence scores
    """
    print(f"Running LLM matching with min confidence {config.MIN_MATCH_CONFIDENCE}...")
    matcher = MarketMatcher()
    
    # Run matching with confidence threshold
    matched_pairs = matcher.match_markets(
        poly_markets, 
        kalshi_markets,
        min_confidence=config.MIN_MATCH_CONFIDENCE
    )
    
    print(f"Found {len(matched_pairs)} high-confidence matches")
    return matched_pairs


def save_matched_markets(matched_pairs: List[Dict], filepath: str):
    """
    Save matched market pairs to CSV.
    
    Args:
        matched_pairs: List of matched pair dictionaries
        filepath: Path to save CSV file
    """
    if not matched_pairs:
        print("No matched markets to save")
        return
    
    matched_at = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    
    with open(filepath, 'w', newline='', encoding='utf-8') as csvfile:
        fieldnames = [
            'id_polymarket', 'id_kalshi', 
            'title_polymarket', 'title_kalshi',
            'confidence', 'expiry_date', 'matched_at'
        ]
        writer = csv.DictWriter(csvfile, fieldnames=fieldnames)
        
        writer.writeheader()
        for pair in matched_pairs:
            market_a = pair['market_a']
            market_b = pair['market_b']
            
            writer.writerow({
                'id_polymarket': market_a.get('id', ''),
                'id_kalshi': market_b.get('id', ''),
                'title_polymarket': market_a.get('title', ''),
                'title_kalshi': market_b.get('title', ''),
                'confidence': pair.get('confidence', 0.0),
                'expiry_date': market_a.get('expiry_date', ''),
                'matched_at': matched_at
            })
    
    print(f"Saved {len(matched_pairs)} matched pairs to {filepath}")


def discover_markets():
    """
    Main function to run the complete market discovery process.
    """
    print("=" * 60)
    print("MARKET DISCOVERY MODULE")
    print("=" * 60)
    
    # Step 1: Scrape all markets
    poly_markets, kalshi_markets = scrape_all_markets()
    
    # Step 2: Save metadata
    save_market_metadata(poly_markets, config.POLYMARKET_ALL_FILE, "Polymarket")
    save_market_metadata(kalshi_markets, config.KALSHI_ALL_FILE, "Kalshi")
    
    # Step 3: Run matching
    matched_pairs = run_matching(poly_markets, kalshi_markets)
    
    # Step 4: Save matched markets
    save_matched_markets(matched_pairs, config.MATCHED_MARKETS_FILE)
    
    print("=" * 60)
    print("Market discovery complete!")
    print(f"Matched markets saved to: {config.MATCHED_MARKETS_FILE}")
    print("=" * 60)


if __name__ == "__main__":
    discover_markets()
