import soccerdata as sd
import logging

# Configure logging
logging.basicConfig(level=logging.INFO)

def inspect_player_data():
    """
    Inspects what player-level data is available via soccerdata (FBref).
    """
    fbref = sd.FBref(leagues="ENG-Premier League", seasons="2324")
    
    # Try creating a generator or fetching a small sample
    # read_player_match_stats returns a MultiIndex DataFrame
    print("Fetching player match stats (sample)...")
    try:
        # We limit to a single match or team to avoid downloading everything
        # Actually, let's just use read_schedule to get a match_id and then see if specific match functions exist
        schedule = fbref.read_schedule()
        if schedule.empty:
            print("No schedule found.")
            return

        print(f"Found {len(schedule)} matches.")
        
        # Available stat types in FBref
        stat_types = ['summary', 'keepers', 'passing', 'defense', 'possession', 'misc']
        
        for stat_type in stat_types:
            print(f"\n--- Fetching {stat_type} stats ---")
            # This downloads ALL player stats for the season/league if we don't be careful
            # But for inspection, we can start the download and interrupt or just fetch it (it might be large)
            # Let's try to fetch just for one match if possible? 
            # soccerdata usually fetches by league/season.
            
            # Use read_player_match_stats for the whole season (it caches)
            df = fbref.read_player_match_stats(stat_type=stat_type)
            print(df.head())
            print(df.columns.tolist())
            break # Just check one type for now to verify connectivity and schema
            
    except Exception as e:
        print(f"Error: {e}")

if __name__ == "__main__":
    inspect_player_data()
