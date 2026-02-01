import pandas as pd
import numpy as np
from scipy.stats import poisson
from typing import Dict, Tuple
from .database import Database
import logging

logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s')
logger = logging.getLogger(__name__)

class PoissonModel:
    def __init__(self):
        self.db = Database()
        self.attack_strength = {}
        self.defense_strength = {}
        self.league_avg_home_goals = 0.0
        self.league_avg_away_goals = 0.0

    def train(self, max_date=None):
        """
        Trains the Poisson model on historical matches.
        If max_date is provided, only uses matches played before that date.
        """
        logger.info(f"Training Poisson model (max_date={max_date})...")
        
        # Fetch all matches
        self.db.connect()
        query = "SELECT date, home_team, away_team, home_score, away_score FROM matches"
        df = pd.read_sql_query(query, self.db.conn)
        self.db.close()
        
        if df.empty:
            logger.warning("No data to train on.")
            return

        # Convert date column
        df['date'] = pd.to_datetime(df['date'])

        # Filter by max_date
        if max_date:
            df = df[df['date'] < pd.to_datetime(max_date)]
            
        if df.empty:
            # logger.warning("No data before max_date.")
            return

        # Calculate league averages using EWM to capture trends
        # We need to sort by date first to interpret EWM correctly as "time series"
        df_sorted = df.sort_values('date')
        
        # We'll use the final EWM value as the current "state" of the league
        # span=38 roughly implies a "season" memory, or maybe shorter for trends?
        # Let's use span=10 matches * 10 games/week? No, span is number of observations.
        # There are 380 games. A span of 40 represents about a month of league play (4 weeks * 10 games).
        league_span = 40 
        self.league_avg_home_goals = df_sorted['home_score'].ewm(span=league_span).mean().iloc[-1]
        self.league_avg_away_goals = df_sorted['away_score'].ewm(span=league_span).mean().iloc[-1]
        
        # Calculate team stats
        teams = pd.concat([df['home_team'], df['away_team']]).unique()
        
        team_span = 10 # 10 games is standard for "form"
        
        for team in teams:
            # Home stats
            home_games = df[df['home_team'] == team].sort_values('date')
            if not home_games.empty:
                avg_home_goals_scored = home_games['home_score'].ewm(span=team_span).mean().iloc[-1]
                avg_home_goals_conceded = home_games['away_score'].ewm(span=team_span).mean().iloc[-1]
            else:
                avg_home_goals_scored = 0 # Default fallback, though should ideally use league avg
                avg_home_goals_conceded = 0
            
            # Away stats
            away_games = df[df['away_team'] == team].sort_values('date')
            if not away_games.empty:
                avg_away_goals_scored = away_games['away_score'].ewm(span=team_span).mean().iloc[-1]
                avg_away_goals_conceded = away_games['home_score'].ewm(span=team_span).mean().iloc[-1]
            else:
                avg_away_goals_scored = 0
                avg_away_goals_conceded = 0
            
            self.attack_strength[team] = {
                'home': avg_home_goals_scored / self.league_avg_home_goals if self.league_avg_home_goals > 0 else 1,
                'away': avg_away_goals_scored / self.league_avg_away_goals if self.league_avg_away_goals > 0 else 1
            }
            
            self.defense_strength[team] = {
                'home': avg_home_goals_conceded / self.league_avg_away_goals if self.league_avg_away_goals > 0 else 1,
                'away': avg_away_goals_conceded / self.league_avg_home_goals if self.league_avg_home_goals > 0 else 1
            }
            
        logger.info(f"Trained on {len(df)} matches. League Avg Home Goals: {self.league_avg_home_goals:.2f}")

    def predict_match(self, home_team: str, away_team: str) -> Dict[str, float]:
        """
        Predicts the outcome probabilities for a match.
        Returns dictionary with 'home_win', 'draw', 'away_win' probabilities.
        """
        if home_team not in self.attack_strength or away_team not in self.attack_strength:
            logger.warning(f"Teams {home_team} or {away_team} not found in training data.")
            return {}

        # Expected Goals
        # Home Goals = Home Attack * Away Defense * League Avg Home Goals
        home_xg = self.attack_strength[home_team]['home'] * self.defense_strength[away_team]['away'] * self.league_avg_home_goals
        
        # Away Goals = Away Attack * Home Defense * League Avg Away Goals
        away_xg = self.attack_strength[away_team]['away'] * self.defense_strength[home_team]['home'] * self.league_avg_away_goals
        
        # Calculate probabilities using Poisson distribution
        # We simulate scores up to 10 goals
        max_goals = 10
        home_probs = [poisson.pmf(i, home_xg) for i in range(max_goals)]
        away_probs = [poisson.pmf(i, away_xg) for i in range(max_goals)]
        
        home_win_prob = 0.0
        draw_prob = 0.0
        away_win_prob = 0.0
        
        for h in range(max_goals):
            for a in range(max_goals):
                prob = home_probs[h] * away_probs[a]
                if h > a:
                    home_win_prob += prob
                elif h == a:
                    draw_prob += prob
                else:
                    away_win_prob += prob
                    
        return {
            'home_team': home_team,
            'away_team': away_team,
            'home_xg': home_xg,
            'away_xg': away_xg,
            'home_win': home_win_prob,
            'draw': draw_prob,
            'away_win': away_win_prob
        }

class DixonColesModel(PoissonModel):
    def __init__(self):
        super().__init__()
        self.rho = 0.0 # Dependence parameter

    def predict_match(self, home_team: str, away_team: str) -> Dict[str, float]:
        """
        Predicts match outcome using Dixon-Coles adjustment.
        """
        base_pred = super().predict_match(home_team, away_team)
        if not base_pred:
            return {}
            
        home_xg = base_pred['home_xg']
        away_xg = base_pred['away_xg']
        
        # Dixon-Coles Adjustment
        # We need to recalculate the probability matrix with the adjustment
        max_goals = 10
        home_probs = [poisson.pmf(i, home_xg) for i in range(max_goals)]
        away_probs = [poisson.pmf(i, away_xg) for i in range(max_goals)]
        
        # Rho correction (using a fixed rho for now, or we can optimize)
        # Literature suggests rho is often around -0.13 for soccer
        self.rho = -0.13 
        
        matrix = np.outer(home_probs, away_probs)
        
        # Apply adjustment factor tau(x, y)
        # tau(0, 0) = 1 - (lambda*mu*rho)
        # tau(0, 1) = 1 + (lambda*rho)
        # tau(1, 0) = 1 + (mu*rho)
        # tau(1, 1) = 1 - rho
        # All others = 1
        
        def tau(x, y, lam, mu, rho):
            if x == 0 and y == 0:
                return 1 - (lam * mu * rho)
            elif x == 0 and y == 1:
                return 1 + (lam * rho)
            elif x == 1 and y == 0:
                return 1 + (mu * rho)
            elif x == 1 and y == 1:
                return 1 - rho
            else:
                return 1.0
                
        # Apply correction to the matrix
        # We only need to correct 0-0, 0-1, 1-0, 1-1
        # But we must ensure probabilities sum to 1? 
        # Dixon-Coles usually doesn't strictly sum to 1 after adjustment without normalization, 
        # but the adjustment is small.
        
        new_matrix = np.zeros((max_goals, max_goals))
        
        for h in range(max_goals):
            for a in range(max_goals):
                correction = tau(h, a, home_xg, away_xg, self.rho)
                new_matrix[h, a] = matrix[h, a] * correction
                
        # Normalize to ensure sum is 1
        new_matrix /= new_matrix.sum()
        
        home_win_prob = np.sum(np.tril(new_matrix, -1))
        draw_prob = np.trace(new_matrix)
        away_win_prob = np.sum(np.triu(new_matrix, 1))
        
        return {
            'home_team': home_team,
            'away_team': away_team,
            'home_xg': home_xg,
            'away_xg': away_xg,
            'home_win': home_win_prob,
            'draw': draw_prob,
            'away_win': away_win_prob
        }

    def predict_ou_btts(self, home_team: str, away_team: str) -> Dict[str, float]:
        """
        Calculates Over/Under 2.5 and BTTS probabilities from the scoreline matrix.
        """
        base_pred = super().predict_match(home_team, away_team)
        if not base_pred:
            return {}
            
        home_xg = base_pred['home_xg']
        away_xg = base_pred['away_xg']
        
        # Rebuild the Dixon-Coles adjusted matrix
        max_goals = 10
        home_probs = [poisson.pmf(i, home_xg) for i in range(max_goals)]
        away_probs = [poisson.pmf(i, away_xg) for i in range(max_goals)]
        
        self.rho = -0.13 
        matrix = np.outer(home_probs, away_probs)
        
        def tau(x, y, lam, mu, rho):
            if x == 0 and y == 0:
                return 1 - (lam * mu * rho)
            elif x == 0 and y == 1:
                return 1 + (lam * rho)
            elif x == 1 and y == 0:
                return 1 + (mu * rho)
            elif x == 1 and y == 1:
                return 1 - rho
            else:
                return 1.0
        
        new_matrix = np.zeros((max_goals, max_goals))
        for h in range(max_goals):
            for a in range(max_goals):
                correction = tau(h, a, home_xg, away_xg, self.rho)
                new_matrix[h, a] = matrix[h, a] * correction
       
        new_matrix /= new_matrix.sum()
        
        # Calculate Over/Under 2.5
        over_2_5 = 0.0
        under_2_5 = 0.0
        btts_yes = 0.0
        btts_no = 0.0
        
        for h in range(max_goals):
            for a in range(max_goals):
                total_goals = h + a
                prob = new_matrix[h, a]
                
                if total_goals > 2.5:
                    over_2_5 += prob
                else:
                    under_2_5 += prob
                
                if h > 0 and a > 0:
                    btts_yes += prob
                else:
                    btts_no += prob
        
        return {
            'home_team': home_team,
            'away_team': away_team,
            'over_2_5': over_2_5,
            'under_2_5': under_2_5,
            'btts_yes': btts_yes,
            'btts_no': btts_no
        }

if __name__ == "__main__":
    model = PoissonModel()
    model.train()
    
    # Test prediction: Man City vs Arsenal (Example)
    # Note: Team names must match exactly what's in the DB (from FBref)
    # Let's try to find correct names first
    print("\n--- Prediction Test ---")
    prediction = model.predict_match("Manchester City", "Arsenal")
    if prediction:
        print(f"Match: {prediction['home_team']} vs {prediction['away_team']}")
        print(f"Expected Goals: {prediction['home_xg']:.2f} - {prediction['away_xg']:.2f}")
        print(f"Probabilities:")
        print(f"  Home Win: {prediction['home_win']:.2%}")
        print(f"  Draw:     {prediction['draw']:.2%}")
        print(f"  Away Win: {prediction['away_win']:.2%}")
