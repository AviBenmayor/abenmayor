import soccerdata as sd
import logging

logging.basicConfig(level=logging.INFO)

def test_single_fetch():
    fbref = sd.FBref(leagues="ENG-Premier League", seasons="2324")
    # match_id from schedule output: 3a6836b4
    try:
        print("Attempting to fetch single match...")
        # Check kwargs support or match_id param
        # The library source code usually reveals this.
        # Often it is match_id=[list]
        df = fbref.read_player_match_stats(match_id='3a6836b4')
        print("Columns:", df.columns.tolist())
        print(df.head())
        print("Success!")
    except TypeError as e:
        print(f"Failed with TypeError: {e}")
    except Exception as e:
        print(f"Failed with {type(e)}: {e}")

if __name__ == "__main__":
    test_single_fetch()
