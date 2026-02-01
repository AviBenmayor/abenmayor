import soccerdata as sd
import logging

logging.basicConfig(level=logging.INFO)

def test_fetch():
    fbref = sd.FBref(leagues="ENG-Premier League", seasons="2324")
    schedule = fbref.read_schedule()
    if schedule.empty:
        print("No schedule.")
        return
        
    # Get first match_id
    # schedule index is usually match_id in recent soccerdata versions?
    # Or 'game_id' column.
    print(schedule.head())
    
    # Pick one ID
    # game_id might be in index or column.
    # Let's try to pass 'force_cache=True' to avoid network if possible?
    
    # Try reading stats for specific match
    # Assuming standard method signature might accept match_id or similar.
    # If not, we are stuck with bulk.
    try:
        # Some SD versions support 'match_id' filtering
        # The logs showed "Retrieving game with id=...". 
        # The underlying method is _download_and_save(url, ...).
        pass
    except:
        pass

if __name__ == "__main__":
    test_fetch()
