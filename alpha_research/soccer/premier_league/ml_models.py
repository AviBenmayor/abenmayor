import pandas as pd
import numpy as np
import xgboost as xgb
from sklearn.model_selection import train_test_split
from sklearn.metrics import accuracy_score, log_loss
from .database import Database
import logging

logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s')
logger = logging.getLogger(__name__)

class MLModel:
    def __init__(self):
        self.db = Database()
        self.model = None
        self.feature_cols = []
        
    def prepare_features(self):
        """
        Loads data and generates features for ML training.
        """
        logger.info("Loading data for feature engineering...")
        self.db.connect()
        
        # Load Matches
        matches = pd.read_sql_query("""
            SELECT id, date, home_team, away_team, home_score, away_score, season 
            FROM matches 
            ORDER BY date
        """, self.db.conn)
        
        # Load Player Stats
        # We might not check player stats if the collector isn't finished yet, 
        # but let's assume valid data exists.
        try:
            player_stats = pd.read_sql_query("SELECT * FROM player_stats", self.db.conn)
        except Exception:
            logger.warning("player_stats table not found or empty. Using only team stats.")
            player_stats = pd.DataFrame()
            
        self.db.close()
        
        matches['date'] = pd.to_datetime(matches['date'])
        
        # Feature Engineering DataFrame
        # We need to compute features *prior* to each match.
        
        df_features = []
        
        teams = pd.concat([matches['home_team'], matches['away_team']]).unique()
        team_stats = {team: [] for team in teams} # Store history
        
        logger.info("Generating features...")
        for idx, row in matches.iterrows():
            match_date = row['date']
            home = row['home_team']
            away = row['away_team']
            
            # --- Generate Features for this match based on history ---
            
            # 1. Team Form (Rolling Averages)
            def get_form(team, history, span=5):
                if not history:
                    return {'xg': 0, 'goals': 0, 'conceded': 0, 'points': 0}
                
                df_hist = pd.DataFrame(history)
                # Filter before match date (already implicit by loop order but good to be safe)
                
                # EWM xG
                xg_avg = df_hist['xg'].ewm(span=span).mean().iloc[-1]
                goals_avg = df_hist['goals'].ewm(span=span).mean().iloc[-1]
                conceded_avg = df_hist['conceded'].ewm(span=span).mean().iloc[-1]
                points_avg = df_hist['points'].ewm(span=span).mean().iloc[-1]
                
                return {
                    'xg': xg_avg,
                    'goals': goals_avg,
                    'conceded': conceded_avg,
                    'points': points_avg
                }
            
            home_form = get_form(home, team_stats[home])
            away_form = get_form(away, team_stats[away])
            
            # 2. Player Features (Aggregated)
            # We want to know if the "Best XI" is available or performing well.
            # Proxy: Weighted average rating/xG of the team's players in the LAST match.
            # This is a bit naive but captures "current player form".
            
            features = {
                'home_form_xg': home_form['xg'],
                'home_form_goals': home_form['goals'],
                'home_form_conceded': home_form['conceded'],
                'home_form_points': home_form['points'],
                
                'away_form_xg': away_form['xg'],
                'away_form_goals': away_form['goals'],
                'away_form_conceded': away_form['conceded'],
                'away_form_points': away_form['points'],
                
                'is_home': 1 # Redundant if model tree handles it, but good for linear benchmarks
            }
            
            # Add Targets
            # 0: Draw, 1: Home Win, 2: Away Win (Mapping for XGBoost)
            if row['home_score'] > row['away_score']:
                target = 1
            elif row['away_score'] > row['home_score']:
                target = 2
            else:
                target = 0
                
            features['target'] = target
            features['date'] = match_date
            
            df_features.append(features)
            
            # --- Update History ---
            # We assume we only know the result AFTER the match predictions 
            # (which is true for the NEXT iteration)
            
            # Add stats to home team history
            # Need to find xG for this match. 
            # We can use the actual match stats if we had them loaded in 'matches' or separate table.
            # For now, let's look up in player_stats or assume we have team_stats table.
            # Wait, I have 'team_stats' table in DB! I should load that.
            
            # Update: Let's fetch team stats for this match ID.
            # This is slow inside loop. Ideally, we pre-join everything.
            pass 
        
        # Optimizing Pre-computation:
        # Load 'team_stats' table: match_id, team, xg, shots...
        self.db.connect()
        ts_df = pd.read_sql_query("SELECT * FROM team_stats", self.db.conn)
        self.db.close()
        
        # Merge matches with team stats
        # Matches has home_team, away_team.
        # We need to map match_id to xG.
        # matches row -> home_xg, away_xg
        
        matches_enriched = matches.copy()
        
        # Helper map match_id + team -> xG
        # ts_df has match_id, team, xg
        ts_indexed = ts_df.set_index(['match_id', 'team'])
        
        # Pre-load player stats for efficiency
        # We need a quick lookup: match_id -> list of players with stats
        try:
            self.db.connect()
            ps_df = pd.read_sql_query("SELECT * FROM player_stats", self.db.conn)
            self.db.close()
            logger.info(f"Loaded {len(ps_df)} player stats rows.")
        except Exception as e:
            logger.error(f"Failed to load player stats: {e}")
            ps_df = pd.DataFrame()
            
        if not ps_df.empty:
            # Join with match dates to allow time-based filtering
            # matches_lookup = matches[['id', 'date']].rename(columns={'id': 'match_id'})
            # ps_df = ps_df.merge(matches_lookup, on='match_id', how='left')
            # Actually, let's just create a big map: Player -> List of (Date, Stat)
            
            # Map valid match_ids to dates
            match_date_map = matches.set_index('id')['date'].to_dict()
            ps_df['date'] = ps_df['match_id'].map(match_date_map)
            ps_df = ps_df.dropna(subset=['date']).sort_values('date')
            
            # Create a dictionary: Team -> Date -> List of Players
            # And Player -> History
            
            # We want "Last Match Lineup" for a Team at a given Date.
            # team_match_history = {team: [ (date, match_id), ... ]}
            team_match_history = {team: [] for team in teams}
            # Fill with match IDs
            # We can use the 'matches' DF for this
            for idx, row in matches.sort_values('date').iterrows():
                team_match_history[row['home_team']].append((row['date'], row['id']))
                team_match_history[row['away_team']].append((row['date'], row['id']))
                
            # Helper to get previous match ID
            def get_last_match_id(team, current_date):
                hist = team_match_history.get(team, [])
                # Find last match before current_date
                # Assuming hist is sorted
                last_id = None
                for d, mid in hist:
                    if d < current_date:
                        last_id = mid
                    else:
                        break
                return last_id

            # Helper to get aggregated player stats from a specific match
            # But we want the "Form" of the players who played in THAT match, 
            # based on THEIR history prior to CURRENT date.
            # That's O(N^2) or worse if we scan player history every time.
            
            # Optimized Approach:
            # Maintain a tailored "Rolling Form" dictionary for every player.
            # player_rolling_stats = {player: {'xg': ewm_obj, 'goals': ewm_obj}} 
            # But EWM object is hard to maintain incrementally without overhead.
            # Simpler: Just Pre-calculate Rolling 5-game avg for every player key intersection?
            
            # Let's pivot ps_df?
            # Creating a 'Player Form Database'
            # ps_df has 10k rows? 380 * 22 = 8360. Small enough.
            
            # Calculate rolling stats for each player
            ps_df['player_roll_xg'] = ps_df.groupby('player')['xg'].transform(lambda x: x.ewm(span=5).mean().shift(1)) # shift 1 to avoid lookahead
            ps_df['player_roll_goals'] = ps_df.groupby('player')['goals'].transform(lambda x: x.ewm(span=5).mean().shift(1))
            
            # Indexed access
            # (match_id, team) -> [List of {player, roll_xg, minutes}]
            # We group by match_id and team to get the lineup of that match
            lineups = ps_df.groupby(['match_id', 'team'])
            
            def get_team_player_form(team, current_date):
                # 1. Get last match ID
                last_mid = get_last_match_id(team, current_date)
                if not last_mid:
                    return 0.0, 0.0 # No history
                
                # 2. Get players who played in that match
                try:
                    squad_stats = lineups.get_group((last_mid, team))
                except KeyError:
                    return 0.0, 0.0
                
                # 3. Aggregate their rolling stats (which were computed relative to THAT match)
                # ERROR: 'player_roll_xg' in ps_df is the rolling average PRIOR to the match in that row.
                # So if we look at Last Match, we get the form ENTERING last match.
                # Ideally we want form ENTERING Current Match.
                # But using "Form entering last match" is a 1-game lag proxy, which is acceptable and safe.
                # OR we could update their form including the last match?
                # Yes, we should use the `values` from the Last Match row to update the EWM?
                # Complex. Let's stick to "Weighted Average of Rolling Form of Players in Last Lineup".
                
                total_min = squad_stats['minutes'].sum()
                if total_min == 0: return 0.0, 0.0
                
                # Weighted average
                weighted_xg = (squad_stats['player_roll_xg'].fillna(0) * squad_stats['minutes']).sum() / total_min
                weighted_goals = (squad_stats['player_roll_goals'].fillna(0) * squad_stats['minutes']).sum() / total_min
                
                return weighted_xg, weighted_goals

        else:
            def get_team_player_form(team, date): return 0.0, 0.0

        history = {team: [] for team in teams}
        final_data = []
        
        for idx, row in matches_enriched.iterrows():
            mid = row['id']
            h_team = row['home_team']
            a_team = row['away_team']
            match_date = row['date']
            
            # 1. Feature Extraction
            h_stats = get_form(h_team, history[h_team])
            a_stats = get_form(a_team, history[a_team])
            
            # Player Stats
            h_pxg, h_pgls = get_team_player_form(h_team, match_date)
            a_pxg, a_pgls = get_team_player_form(a_team, match_date)
            
            feat = {
                'match_id': mid,
                'date': match_date,
                'home_roll_xg': h_stats['xg'],
                'home_roll_gls': h_stats['goals'],
                'home_roll_pts': h_stats['points'],
                'home_player_xg': h_pxg,
                'home_player_gls': h_pgls,
                
                'away_roll_xg': a_stats['xg'],
                'away_roll_gls': a_stats['goals'],
                'away_roll_pts': a_stats['points'],
                'away_player_xg': a_pxg,
                'away_player_gls': a_pgls,
                
                'target': 1 if row['home_score'] > row['away_score'] else (2 if row['away_score'] > row['home_score'] else 0)
            }
            final_data.append(feat)
            
            # 2. Update History (using Current Result)
            # Get actual stats from ts_indexed
            try:
                h_xg = ts_indexed.loc[(mid, h_team), 'xg']
            except KeyError:
                h_xg = 0.0 # Missing data
            
            try:
                a_xg = ts_indexed.loc[(mid, a_team), 'xg']
            except KeyError:
                a_xg = 0.0
            
            h_pts = 3 if row['home_score'] > row['away_score'] else (1 if row['home_score'] == row['away_score'] else 0)
            a_pts = 3 if row['away_score'] > row['home_score'] else (1 if row['away_score'] == row['home_score'] else 0)
            
            history[h_team].append({
                'xg': h_xg,
                'goals': row['home_score'],
                'conceded': row['away_score'],
                'points': h_pts
            })
            
            history[a_team].append({
                'xg': a_xg,
                'goals': row['away_score'],
                'conceded': row['home_score'],
                'points': a_pts
            })
            
        return pd.DataFrame(final_data)

    def train_and_eval(self):
        data = self.prepare_features()
        if data.empty:
            logger.warning("No data.")
            return

        # Time-based split
        # Train on first 70%, Test on last 30%
        # Or better: Walk-forward validation.
        # Simple for now: Split by date.
        
        split_date = pd.to_datetime('2024-03-01')
        train = data[data['date'] < split_date]
        test = data[data['date'] >= split_date]
        
        features = [c for c in data.columns if c not in ['match_id', 'date', 'target']]
        self.feature_cols = features
        
        X_train = train[features]
        y_train = train['target']
        X_test = test[features]
        y_test = test['target']
        
        dtrain = xgb.DMatrix(X_train, label=y_train)
        dtest = xgb.DMatrix(X_test, label=y_test)
        
        params = {
            'max_depth': 4,
            'eta': 0.1,
            'objective': 'multi:softprob',
            'num_class': 3,
            'eval_metric': 'mlogloss'
        }
        
        bst = xgb.train(params, dtrain, num_boost_round=100)
        
        # Eval
        preds = bst.predict(dtest)
        y_pred_class = np.argmax(preds, axis=1)
        acc = accuracy_score(y_test, y_pred_class)
        loss = log_loss(y_test, preds)
        
        logger.info(f"XGBoost Test Accuracy: {acc:.2%}")
        logger.info(f"Log Loss: {loss:.4f}")
        
        # Feature Importance
        imp = bst.get_score(importance_type='gain')
        sorted_imp = sorted(imp.items(), key=lambda x: x[1], reverse=True)
        logger.info("Top Features:")
        for k, v in sorted_imp[:5]:
            logger.info(f"{k}: {v:.2f}")
            
        return bst, X_test, y_test, test

    def backtest(self):
        bst, X_test, y_test, test_df = self.train_and_eval()
        
        logger.info("Running ML Backtest...")
        
        # Predict probabilities
        dtest = xgb.DMatrix(X_test)
        probs = bst.predict(dtest)
        
        # Load Odds for Test Set
        # test_df has match_id
        match_ids = test_df['match_id'].tolist()
        if not match_ids:
            return
            
        placeholders = ','.join(['?'] * len(match_ids))
        self.db.connect()
        odds_query = f"""
            SELECT match_id, bookmaker, home_win, draw, away_win 
            FROM odds 
            WHERE bookmaker = 'Bet365' AND match_id IN ({placeholders})
        """
        odds_df = pd.read_sql_query(odds_query, self.db.conn, params=match_ids)
        self.db.close()
        
        # Merge odds
        test_df = test_df.merge(odds_df, on='match_id', how='inner')
        
        bankroll = 10000.0
        stake = 100.0
        bets = 0
        wins = 0
        
        # Evaluate bets
        # probs is array of [prob_draw, prob_home, prob_away] (0, 1, 2)
        # Wait, check class mapping:
        # In prepare_features: 
        # target = 1 (Home > Away) -> Home Win
        # target = 2 (Away > Home) -> Away Win
        # target = 0 (Draw)
        
        # XGBoost outputs are usually ordered by class label: 0, 1, 2.
        # So probs[i][0] = Draw, probs[i][1] = Home, probs[i][2] = Away.
        
        history = []
        
        # Reset index to align with probs
        test_df = test_df.reset_index(drop=True)
        
        for idx, row in test_df.iterrows():
            # Get model probs
            p_draw = probs[idx][0]
            p_home = probs[idx][1]
            p_away = probs[idx][2]
            
            # Betting logic (Kelly or Fixed Edge)
            edge_threshold = 0.05
            
            # Home
            if row['home_win'] > 1.0:
                implied_h = 1.0 / row['home_win']
                edge_h = p_home - implied_h
                if edge_h > edge_threshold:
                    # Place Home Bet
                    outcome = 1 if row['target'] == 1 else 0 # 1 is Home Win
                    pnl = stake * (row['home_win'] - 1) if outcome else -stake
                    bankroll += pnl
                    bets += 1
                    if outcome: wins += 1
                    continue # One bet per match? Or multiple? Let's do one max for simplicity.
            
            # Draw
            if row['draw'] > 1.0:
                implied_d = 1.0 / row['draw']
                edge_d = p_draw - implied_d
                if edge_d > edge_threshold:
                    outcome = 1 if row['target'] == 0 else 0
                    pnl = stake * (row['draw'] - 1) if outcome else -stake
                    bankroll += pnl
                    bets += 1
                    if outcome: wins += 1
                    continue
                    
            # Away
            if row['away_win'] > 1.0:
                implied_a = 1.0 / row['away_win']
                edge_a = p_away - implied_a
                if edge_a > edge_threshold:
                    outcome = 1 if row['target'] == 2 else 0
                    pnl = stake * (row['away_win'] - 1) if outcome else -stake
                    bankroll += pnl
                    bets += 1
                    if outcome: wins += 1
                    continue
        
        roi = ((bankroll - 10000.0) / (bets * stake)) * 100 if bets > 0 else 0
        logger.info(f"ML Backtest Results:")
        logger.info(f"Bets: {bets}")
        logger.info(f"Win Rate: {wins/bets:.2%}" if bets > 0 else "0%")
        logger.info(f"ROI: {roi:.2f}%")
        logger.info(f"Final Bankroll: ${bankroll:.2f}")

if __name__ == "__main__":
    ml = MLModel()
    ml.backtest()
