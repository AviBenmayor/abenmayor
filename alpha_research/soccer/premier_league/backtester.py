import pandas as pd
import numpy as np
from .database import Database
from .models import PoissonModel, DixonColesModel
import logging
from datetime import timedelta

logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s')
logger = logging.getLogger(__name__)

class Backtester:
    def __init__(self, start_date='2023-09-01', bankroll=10000.0, stake_size=100.0):
        self.db = Database()
        self.model = DixonColesModel() # Use Dixon-Coles
        self.start_date = pd.to_datetime(start_date)
        self.bankroll = bankroll
        self.stake_size = stake_size
        self.history = []

    def run(self):
        """Runs the backtest simulation."""
        logger.info("Starting backtest...")
        
        # Fetch all matches and odds
        self.db.connect()
        # Join matches and odds
        query = """
            SELECT m.id, m.date, m.home_team, m.away_team, m.home_score, m.away_score,
                   o.home_win as odd_h, o.draw as odd_d, o.away_win as odd_a, o.bookmaker
            FROM matches m
            JOIN odds o ON m.id = o.match_id
            WHERE o.bookmaker = 'Bet365'
            ORDER BY m.date ASC
        """
        data = pd.read_sql_query(query, self.db.conn)
        self.db.close()
        
        data['date'] = pd.to_datetime(data['date'])
        
        # Filter matches after start_date (give model some data to train on first)
        test_matches = data[data['date'] >= self.start_date]
        
        logger.info(f"Backtesting on {len(test_matches)} matches starting from {self.start_date.date()}")
        
        total_bets = 0
        wins = 0
        
        # Iterate through matches
        # Optimization: Re-train model weekly instead of every match to save time?
        # For 380 matches, every match is fine.
        
        current_date = None
        
        for idx, row in test_matches.iterrows():
            match_date = row['date']
            
            # Re-train model if it's a new day (or just every match, but let's do new day for efficiency)
            if current_date != match_date:
                self.model.train(max_date=match_date)
                current_date = match_date
            
            # Predict
            pred = self.model.predict_match(row['home_team'], row['away_team'])
            if not pred:
                continue
                
            # Betting Logic (Value Betting)
            # Edge = Model_Prob - Implied_Prob
            # Implied_Prob = 1 / Odds
            
            bets = []
            
            # Home Win
            if row['odd_h'] > 1.0:
                implied_h = 1.0 / row['odd_h']
                edge_h = pred['home_win'] - implied_h
                if edge_h > 0.10: # 10% edge threshold
                    bets.append(('H', row['odd_h'], pred['home_win'], edge_h))
            
            # Draw
            if row['odd_d'] > 1.0:
                implied_d = 1.0 / row['odd_d']
                edge_d = pred['draw'] - implied_d
                if edge_d > 0.10:
                    bets.append(('D', row['odd_d'], pred['draw'], edge_d))
                    
            # Away Win
            if row['odd_a'] > 1.0:
                implied_a = 1.0 / row['odd_a']
                edge_a = pred['away_win'] - implied_a
                if edge_a > 0.10:
                    bets.append(('A', row['odd_a'], pred['away_win'], edge_a))
            
            # Execute Bets
            # Result: H, D, A
            result = 'D'
            if row['home_score'] > row['away_score']:
                result = 'H'
            elif row['away_score'] > row['home_score']:
                result = 'A'
                
            for bet_type, odds, prob, edge in bets:
                total_bets += 1
                wager = self.stake_size # Flat staking for now
                
                pnl = -wager
                if bet_type == result:
                    pnl = wager * (odds - 1)
                    wins += 1
                
                self.bankroll += pnl
                
                self.history.append({
                    'date': match_date,
                    'match': f"{row['home_team']} vs {row['away_team']}",
                    'bet': bet_type,
                    'odds': odds,
                    'prob': prob,
                    'edge': edge,
                    'result': result,
                    'pnl': pnl,
                    'bankroll': self.bankroll
                })
        
        # Summary
        roi = ((self.bankroll - 10000.0) / (total_bets * self.stake_size)) * 100 if total_bets > 0 else 0
        logger.info(f"Backtest Complete.")
        logger.info(f"Total Bets: {total_bets}")
        logger.info(f"Win Rate: {wins/total_bets:.2%}" if total_bets > 0 else "Win Rate: 0%")
        logger.info(f"Final Bankroll: ${self.bankroll:.2f}")
        logger.info(f"ROI: {roi:.2f}%")
        
        return pd.DataFrame(self.history)

if __name__ == "__main__":
    backtester = Backtester()
    df = backtester.run()
    if not df.empty:
        print(df.tail())
