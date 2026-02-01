import time
import logging
from typing import List
# Updated imports to point to the shared market_data package
from alpha_research.market_data.polymarket import PolymarketClient
from alpha_research.market_data.kalshi import KalshiClient
from .database import Database

logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s')
logger = logging.getLogger(__name__)

class MarketRecorder:
    def __init__(self):
        self.db = Database()
        self.polymarket = PolymarketClient()
        self.kalshi = KalshiClient()

    def record_snapshots(self):
        """Fetches current markets from all sources and saves snapshots."""
        logger.info("Starting market recording cycle...")
        
        # Fetch Polymarket
        try:
            logger.info("Fetching Polymarket data...")
            poly_markets = self.polymarket.fetch_markets()
            logger.info(f"Found {len(poly_markets)} active markets on Polymarket")
            
            # Filter for Premier League if possible, or just save all for now and filter later
            # The clients currently fetch 'active' markets. 
            # We might want to add keyword filtering here to reduce noise.
            soccer_keywords = ["Premier League", "Soccer", "Football", "Man City", "Liverpool", "Arsenal", "Man Utd", "Chelsea"]
            
            count = 0
            for raw_market in poly_markets:
                market = self.polymarket.normalize_data(raw_market)
                logger.info(f"Polymarket Candidate: {market['title']}")
                
                # Basic keyword filter
                if any(k.lower() in market['title'].lower() for k in soccer_keywords):
                    self.db.save_market_snapshot(market)
                    count += 1
            
            logger.info(f"Saved {count} relevant Polymarket snapshots")
            
        except Exception as e:
            logger.error(f"Error recording Polymarket: {e}")

        # Fetch Kalshi
        try:
            logger.info("Fetching Kalshi data...")
            kalshi_markets = self.kalshi.fetch_markets()
            logger.info(f"Found {len(kalshi_markets)} active markets on Kalshi")
            
            count = 0
            for raw_market in kalshi_markets:
                market = self.kalshi.normalize_data(raw_market)
                logger.info(f"Kalshi Candidate: {market['title']}")
                
                # Basic keyword filter
                if any(k.lower() in market['title'].lower() for k in soccer_keywords):
                    self.db.save_market_snapshot(market)
                    count += 1
            
            logger.info(f"Saved {count} relevant Kalshi snapshots")
            
        except Exception as e:
            logger.error(f"Error recording Kalshi: {e}")
            
        logger.info("Recording cycle complete.")

if __name__ == "__main__":
    recorder = MarketRecorder()
    recorder.record_snapshots()
