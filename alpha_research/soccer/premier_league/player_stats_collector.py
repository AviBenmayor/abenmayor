import soccerdata as sd
import pandas as pd
from .database import Database
import logging
import time
import random

logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s')
logger = logging.getLogger(__name__)

def fetch_and_save_player_stats_incremental():
    """
    Fetches player match stats from FBref match by match and saves to database.
    """
    db = Database()
    fbref = sd.FBref(leagues="ENG-Premier League", seasons="2324")
    
    logger.info("Fetching schedule...")
    schedule = fbref.read_schedule()
    
    # Check for game_id presence
    if 'game_id' not in schedule.columns:
        # Sometimes it's in the index?
        schedule = schedule.reset_index()
        if 'game_id' not in schedule.columns:
            logger.error("Could not find 'game_id' in schedule.")
            return

    game_ids = schedule['game_id'].unique()
    logger.info(f"Found {len(game_ids)} matches.")
    
    # Helper to map team names
    def clean_team_name(name):
        mapping = {
            "Brighton & Hove Albion": "Brighton",
            "West Ham United": "West Ham",
            "Tottenham Hotspur": "Tottenham",
            "Wolverhampton Wanderers": "Wolves",
            "Nottingham Forest": "Nott'ham Forest",
            "Sheffield United": "Sheffield Utd",
            "Luton Town": "Luton",
            "Manchester United": "Man United",
            "Newcastle United": "Newcastle"
        }
        return mapping.get(name, name)

    # Check existing data to skip
    db.connect()
    existing_matches = pd.read_sql_query("SELECT DISTINCT match_id FROM player_stats", db.conn)
    db.close()
    
    # We store match_id as YYYY-MM-DD_Home_Away.
    # But here we iterate by game_id. 
    # To check if we already have it, we need to know the mapping or just try to insert (REPLACE is fine).
    # Since we can't easily map game_id -> our match_id without fetching, 
    # we'll just process everything. The REPLACE query handles duplicates.
    # Optimization: If we trust the order, we could skip?
    # No, let's just run it. Cached ones are fast.

    processed_count = 0
    
    # Iterate through schedule to get context
    # schedule has index or columns: 'date', 'home_team', 'away_team', 'game_id'
    
    for idx, row in schedule.iterrows():
        try:
            game_id = row['game_id']
            date_val = row['date']
            home_team = row['home_team']
            away_team = row['away_team']
            
            # Construct match_id upfront
            date_str = date_val.strftime('%Y-%m-%d')
            home_clean = clean_team_name(home_team)
            away_clean = clean_team_name(away_team)
            match_id = f"{date_str}_{home_clean}_{away_clean}".replace(" ", "")
            
            processed_count += 1
            # Optimization: check if stats exist for this match_id
            # if match_id in existing_matches['match_id'].values:
            #     continue 
            
            logger.info(f"[{processed_count}/{len(schedule)}] Processing {match_id} (game_id={game_id})...")
            
            # Fetch stats
            df = fbref.read_player_match_stats(match_id=game_id, stat_type="summary")
            
            if df.empty:
                logger.warning(f"No stats for {game_id}")
                continue
                
            df = df.reset_index()
            
            # Flatten columns
            # Columns are like ('Performance', 'Gls') or ('min', '')
            # We join them with '_'
            df.columns = ['_'.join(col).strip('_') for col in df.columns.values]
            
            stats_batch = []
            
            for _, p_row in df.iterrows():
                # Team name in p_row is player's team.
                p_team = clean_team_name(p_row['team'])
                p_pos = p_row.get('pos', '')
                
                try:
                    # Map flattened names to DB columns
                    # min -> min
                    # Performance_Gls -> goals
                    # Performance_Ast -> assists
                    # Performance_Sh -> shots
                    # Performance_SoT -> shots_on_target
                    # Expected_xG -> xg
                    # Expected_xAG -> xa
                    # Expected_npxG -> npxg
                    
                    minutes = int(p_row.get('min', 0))
                    goals = int(p_row.get('Performance_Gls', 0))
                    assists = int(p_row.get('Performance_Ast', 0))
                    shots = int(p_row.get('Performance_Sh', 0))
                    sot = int(p_row.get('Performance_SoT', 0))
                    xg = float(p_row.get('Expected_xG', 0.0)) if not pd.isna(p_row.get('Expected_xG')) else 0.0
                    xa = float(p_row.get('Expected_xAG', 0.0)) if not pd.isna(p_row.get('Expected_xAG')) else 0.0
                    npxg = float(p_row.get('Expected_npxG', 0.0)) if not pd.isna(p_row.get('Expected_npxG')) else 0.0
                except ValueError:
                    continue
                
                stats_batch.append({
                    'team': p_team,
                    'player': p_row['player'],
                    'position': p_pos,
                    'minutes': minutes,
                    'goals': goals,
                    'assists': assists,
                    'shots': shots,
                    'shots_on_target': sot,
                    'xg': xg,
                    'xa': xa,
                    'npxg': npxg
                })
            
            if stats_batch:
                db.save_player_stats(match_id, stats_batch)
                
        except Exception as e:
            logger.error(f"Error processing {row.get('game_id')}: {e}")
            continue

    logger.info("Incremental import complete.")

if __name__ == "__main__":
    fetch_and_save_player_stats_incremental()
