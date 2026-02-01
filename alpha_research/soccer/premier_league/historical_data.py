import soccerdata as sd
import pandas as pd
import logging
import time
from pathlib import Path
from .database import Database

logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s')
logger = logging.getLogger(__name__)

class HistoricalDataCollector:
    def __init__(self, seasons: list = ['2324']):
        self.seasons = seasons
        self.db = Database()
        # Initialize FBref scraper
        logger.info(f"Initializing FBref scraper for seasons: {seasons}")
        self.fbref = sd.FBref(leagues=['ENG-Premier League'], seasons=seasons)

    def fetch_and_save_season_data(self):
        """Fetches match schedule and stats, then saves to DB."""
        try:
            logger.info("Fetching match schedule...")
            schedule = self.fbref.read_schedule()
            
            # Filter for completed matches
            # Check if 'score' exists and is not null
            if 'score' in schedule.columns:
                completed_matches = schedule[schedule['score'].notna()]
            else:
                logger.warning("No 'score' column found in schedule.")
                return
                
            logger.info(f"Found {len(completed_matches)} completed matches.")
            
            # We iterate through the schedule to save matches
            for idx, row in completed_matches.iterrows():
                # idx is usually (league, season, game_id)
                league, season, game_id = idx
                
                date = row['date']
                home_team = row['home_team']
                away_team = row['away_team']
                
                # Parse score "H-A"
                score = row['score']
                try:
                    home_score, away_score = map(int, str(score).split('–')) # Note: might be en-dash or hyphen
                except ValueError:
                    try:
                        home_score, away_score = map(int, str(score).split('-'))
                    except ValueError:
                        logger.warning(f"Could not parse score: {score} for {home_team} vs {away_team}")
                        continue
                
                match_id = f"{date.strftime('%Y-%m-%d')}_{home_team}_{away_team}".replace(" ", "")
                
                match_data = {
                    'id': match_id,
                    'date': date.to_pydatetime() if hasattr(date, 'to_pydatetime') else date,
                    'home_team': str(home_team),
                    'away_team': str(away_team),
                    'home_score': int(home_score),
                    'away_score': int(away_score),
                    'season': str(season)
                }
                
                # Extract stats
                home_xg = row.get('home_xg', 0.0)
                away_xg = row.get('away_xg', 0.0)
                
                # Handle NaN xG
                if pd.isna(home_xg): home_xg = 0.0
                if pd.isna(away_xg): away_xg = 0.0
                
                # Construct stats objects (simplified for now)
                home_stats = {
                    'team': str(home_team),
                    'xg': float(home_xg),
                    'shots': 0, # Need deeper scrape for this
                    'shots_on_target': 0,
                    'corners': 0,
                    'possession': 0.0
                }
                
                away_stats = {
                    'team': str(away_team),
                    'xg': float(away_xg),
                    'shots': 0,
                    'shots_on_target': 0,
                    'corners': 0,
                    'possession': 0.0
                }
                
                self.db.save_match_stats(match_data, home_stats, away_stats)
                
            logger.info("Historical data import complete.")
            
        except Exception as e:
            logger.error(f"Error fetching historical data: {e}")
            import traceback
            traceback.print_exc()

if __name__ == "__main__":
    # Fetch last season (2023-2024)
    collector = HistoricalDataCollector(seasons=['2324'])
    collector.fetch_and_save_season_data()
