import soccerdata as sd
import pandas as pd
import logging
import time
from pathlib import Path
from .database import Database

logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s')
logger = logging.getLogger(__name__)

class OddsCollector:
    def __init__(self, season: str = '2324'):
        self.season = season
        self.db = Database()
        self.csv_url = f"https://www.football-data.co.uk/mmz4281/{season}/E0.csv"

    def fetch_and_save_odds(self):
        """Fetches historical odds from football-data.co.uk and saves to DB."""
        try:
            logger.info(f"Downloading odds from {self.csv_url}...")
            # Read CSV directly into DataFrame
            df = pd.read_csv(self.csv_url)
            
            logger.info(f"Found {len(df)} odds entries.")
            
            # Iterate and save
            for idx, row in df.iterrows():
                # Date format in CSV is usually dd/mm/yyyy
                date_str = row['Date']
                try:
                    date = pd.to_datetime(date_str, dayfirst=True)
                except:
                    logger.warning(f"Could not parse date: {date_str}")
                    continue
                
                home_team = row['HomeTeam']
                away_team = row['AwayTeam']
                
                # Team Name Mapping
                # FBref and Football-Data use slightly different names
                # We need a simple mapper or fuzzy match. 
                # Let's try to match by creating the ID and if it fails, we log it.
                # But wait, we need to match the ID we created in historical_data.py
                # ID format: YYYY-MM-DD_HomeTeam_AwayTeam
                
                # Mappings for common mismatches
                team_map = {
                    "Man City": "Manchester City",
                    "Man United": "Manchester Utd",
                    "Nott'm Forest": "Nott'ham Forest",
                    "Sheffield United": "Sheffield Utd",
                    "Luton": "Luton Town",
                    "Spurs": "Tottenham"
                }
                
                home_team_mapped = team_map.get(home_team, home_team)
                away_team_mapped = team_map.get(away_team, away_team)
                
                match_id = f"{date.strftime('%Y-%m-%d')}_{home_team_mapped}_{away_team_mapped}".replace(" ", "")
                
                # Bet365 Odds - 1x2
                home_win = row.get('B365H')
                draw = row.get('B365D')
                away_win = row.get('B365A')
                
                # Bet365 Odds - Over/Under 2.5
                over_2_5 = row.get('B365>2.5')
                under_2_5 = row.get('B365<2.5')
                
                # BTTS (Both Teams To Score)
                # Note: CSV may use different column names like 'BbAHh' or might not have BTTS
                # Let's check common variations
                btts_yes = row.get('BbMxAHY')  # Max BTTS Yes
                btts_no = row.get('BbMxAHN')   # Max BTTS No
                
                if pd.isna(home_win):
                    continue
                    
                self.db.save_odds(
                    match_id, 
                    "Bet365", 
                    float(home_win), 
                    float(draw), 
                    float(away_win),
                    float(over_2_5) if not pd.isna(over_2_5) else None,
                    float(under_2_5) if not pd.isna(under_2_5) else None,
                    float(btts_yes) if not pd.isna(btts_yes) else None,
                    float(btts_no) if not pd.isna(btts_no) else None
                )
                
            logger.info("Odds import complete.")
            
        except Exception as e:
            logger.error(f"Error fetching odds: {e}")
            import traceback
            traceback.print_exc()

if __name__ == "__main__":
    collector = OddsCollector(season='2324')
    collector.fetch_and_save_odds()
