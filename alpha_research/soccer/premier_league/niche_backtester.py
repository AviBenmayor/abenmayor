import pandas as pd
import numpy as np
from .database import Database
from .models import DixonColesModel
import logging

logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s')
logger = logging.getLogger(__name__)

class NicheBacktester:
    def __init__(self, start_date='2023-09-01', bankroll=10000.0, stake_size=100.0):
        self.db = Database()
        self.model = DixonColesModel()
        self.start_date = pd.to_datetime(start_date)
        self.bankroll = bankroll
        self.stake_size = stake_size
        self.history = []

    def run(self):
        """Runs the backtest on niche markets (O/U and BTTS)."""
        logger.info("Starting niche markets backtest...")
        
        # Fetch all matches and odds
        self.db.connect()
        query = """
            SELECT m.id, m.date, m.home_team, m.away_team, m.home_score, m.away_score,
                   o.over_2_5, o.under_2_5, o.btts_yes, o.btts_no, o.bookmaker
            FROM matches m
            JOIN odds o ON m.id = o.match_id
            WHERE o.bookmaker = 'Bet365' AND o.over_2_5 IS NOT NULL
            ORDER BY m.date ASC
        """
        data = pd.read_sql_query(query, self.db.conn)
        self.db.close()
        
        data['date'] = pd.to_datetime(data['date'])
        
        test_matches = data[data['date'] >= self.start_date]
        logger.info(f"Backtesting on {len(test_matches)} matches starting from {self.start_date.date()}")
        
        total_bets = 0
        wins = 0
        current_date = None
        
        for idx, row in test_matches.iterrows():
            match_date = row['date']
            
            # Re-train model daily
            if current_date != match_date:
                self.model.train(max_date=match_date)
                current_date = match_date
            
            # Predict niche markets
            pred = self.model.predict_ou_btts(row['home_team'], row['away_team'])
            if not pred:
                continue
            
            # Betting Logic
            bets = []
            
            # Over 2.5
            if row['over_2_5'] and row['over_2_5'] > 1.0:
                implied = 1.0 / row['over_2_5']
                edge = pred['over_2_5'] - implied
                if edge > 0.05:  # 5% edge threshold
                    bets.append(('O2.5', row['over_2_5'], pred['over_2_5'], edge))
            
            # Under 2.5
            if row['under_2_5'] and row['under_2_5'] > 1.0:
                implied = 1.0 / row['under_2_5']
                edge = pred['under_2_5'] - implied
                if edge > 0.05:
                    bets.append(('U2.5', row['under_2_5'], pred['under_2_5'], edge))
            
            # BTTS Yes (if available)
            if row['btts_yes'] and row['btts_yes'] > 1.0:
                implied = 1.0 / row['btts_yes']
                edge = pred['btts_yes'] - implied
                if edge > 0.05:
                    bets.append(('BTTS_Y', row['btts_yes'], pred['btts_yes'], edge))
            
            # BTTS No (if available)
            if row['btts_no'] and row['btts_no'] > 1.0:
                implied = 1.0 / row['btts_no']
                edge = pred['btts_no'] - implied
                if edge > 0.05:
                    bets.append(('BTTS_N', row['btts_no'], pred['btts_no'], edge))
            
            # Determine results
            total_goals = row['home_score'] + row['away_score']
            result_ou = 'O2.5' if total_goals > 2.5 else 'U2.5'
            result_btts = 'BTTS_Y' if (row['home_score'] > 0 and row['away_score'] > 0) else 'BTTS_N'
            
            # Execute Bets
            for bet_type, odds, prob, edge in bets:
                total_bets += 1
                wager = self.stake_size
                
                pnl = -wager
                won = False
                
                if bet_type in ['O2.5', 'U2.5']:
                    if bet_type == result_ou:
                        pnl = wager * (odds - 1)
                        won = True
                        wins += 1
                elif bet_type in ['BTTS_Y', 'BTTS_N']:
                    if bet_type == result_btts:
                        pnl = wager * (odds - 1)
                        won = True
                        wins += 1
                
                self.bankroll += pnl
                
                self.history.append({
                    'date': match_date,
                    'match': f"{row['home_team']} vs {row['away_team']}",
                    'bet': bet_type,
                    'odds': odds,
                    'prob': prob,
                    'edge': edge,
                    'won': won,
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
    backtester = NicheBacktester()
    df = backtester.run()
    if not df.empty:
        print("\n--- Bet Breakdown ---")
        print(df.groupby('bet')['won'].agg(['count', 'sum', 'mean']))
        print(df.tail(10))
