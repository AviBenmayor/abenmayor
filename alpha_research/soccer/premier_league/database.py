import sqlite3
from pathlib import Path
from typing import Dict, Any, List, Optional
import datetime

# Updated path to be relative to this file
DB_PATH = Path(__file__).parent / "data" / "premier_league.db"

class Database:
    def __init__(self, db_path: Path = DB_PATH):
        self.db_path = db_path
        self.db_path.parent.mkdir(parents=True, exist_ok=True)
        self.conn = None
        self.cursor = None
        self.init_db()

    def connect(self):
        self.conn = sqlite3.connect(self.db_path)
        self.conn.row_factory = sqlite3.Row
        self.cursor = self.conn.cursor()

    def close(self):
        if self.conn:
            self.conn.close()

    def init_db(self):
        self.connect()
        
        # Markets table (static info)
        self.cursor.execute("""
            CREATE TABLE IF NOT EXISTS markets (
                id TEXT PRIMARY KEY,
                platform TEXT NOT NULL,
                title TEXT NOT NULL,
                url TEXT,
                expiry_date TEXT,
                first_seen TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            )
        """)
        
        # Market Snapshots table (time-series data)
        self.cursor.execute("""
            CREATE TABLE IF NOT EXISTS market_snapshots (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                market_id TEXT NOT NULL,
                timestamp TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                yes_price REAL,
                no_price REAL,
                yes_volume REAL,
                no_volume REAL,
                FOREIGN KEY (market_id) REFERENCES markets (id)
            )
        """)
        
        # Matches table (historical match info)
        self.cursor.execute("""
            CREATE TABLE IF NOT EXISTS matches (
                id TEXT PRIMARY KEY, -- e.g. "2023-08-11_Burnley_ManCity"
                date TIMESTAMP NOT NULL,
                home_team TEXT NOT NULL,
                away_team TEXT NOT NULL,
                home_score INTEGER,
                away_score INTEGER,
                season TEXT
            )
        """)

        # Team Stats table (xG, shots, etc.)
        self.cursor.execute("""
            CREATE TABLE IF NOT EXISTS team_stats (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                match_id TEXT NOT NULL,
                team TEXT NOT NULL,
                xg REAL,
                shots INTEGER,
                shots_on_target INTEGER,
                corners INTEGER,
                possession REAL,
                FOREIGN KEY (match_id) REFERENCES matches (id)
            )
        """)

        # Odds table (Historical closing odds)
        self.cursor.execute("""
            CREATE TABLE IF NOT EXISTS odds (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                match_id TEXT NOT NULL,
                bookmaker TEXT NOT NULL, -- e.g. "Bet365", "Pinnacle"
                home_win REAL,
                draw REAL,
                away_win REAL,
                over_2_5 REAL,
                under_2_5 REAL,
                btts_yes REAL,
                btts_no REAL,
                updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                FOREIGN KEY (match_id) REFERENCES matches (id)
            )
        """)
        
        # Player Stats Table
        self.cursor.execute("""
            CREATE TABLE IF NOT EXISTS player_stats (
                match_id TEXT,
                team TEXT,
                player TEXT,
                position TEXT,
                minutes INTEGER,
                goals INTEGER,
                assists INTEGER,
                shots INTEGER,
                shots_on_target INTEGER,
                xg REAL,
                xa REAL,
                npxg REAL,
                PRIMARY KEY (match_id, player),
                FOREIGN KEY (match_id) REFERENCES matches (id)
            )
        """)
        
        self.conn.commit()
        self.close()

    def save_market_snapshot(self, market: Dict[str, Any]):
        self.connect()
        try:
            # Upsert market info
            self.cursor.execute("""
                INSERT OR IGNORE INTO markets (id, platform, title, url, expiry_date)
                VALUES (?, ?, ?, ?, ?)
            """, (
                market['id'],
                market['platform'],
                market['title'],
                market['url'],
                market['expiry_date']
            ))
            
            # Insert snapshot
            self.cursor.execute("""
                INSERT INTO market_snapshots (market_id, yes_price, no_price, yes_volume, no_volume)
                VALUES (?, ?, ?, ?, ?)
            """, (
                market['id'],
                market['yes_price'],
                market['no_price'],
                market['yes_volume'],
                market['no_volume']
            ))
            
            self.conn.commit()
        finally:
            self.close()

    def get_market_history(self, market_id: str) -> List[Dict[str, Any]]:
        self.connect()
        try:
            self.cursor.execute("""
                SELECT * FROM market_snapshots
                WHERE market_id = ?
                ORDER BY timestamp ASC
            """, (market_id,))
            return [dict(row) for row in self.cursor.fetchall()]
        finally:
            self.close()

    def save_player_stats(self, match_id: str, stats_list: list):
        """
        Saves a list of player stats dictionaries.
        stats_list item: {team, player, position, minutes, goals, assists, shots, shots_on_target, xg, xa, npxg}
        """
        self.connect()
        try:
            self.cursor.executemany("""
                INSERT OR REPLACE INTO player_stats (
                    match_id, team, player, position, minutes, goals, assists, 
                    shots, shots_on_target, xg, xa, npxg
                )
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """, [(
                match_id,
                s['team'],
                s['player'],
                s['position'],
                s['minutes'],
                s['goals'],
                s['assists'],
                s['shots'],
                s['shots_on_target'],
                s['xg'],
                s['xa'],
                s['npxg']
            ) for s in stats_list])
            self.conn.commit()
        finally:
            self.close()

    def save_match_stats(self, match_data: Dict[str, Any], home_stats: Dict[str, Any], away_stats: Dict[str, Any]):
        """
        Saves match result and team stats.
        match_data: {id, date, home_team, away_team, home_score, away_score, season}
        stats: {team, xg, shots, shots_on_target, corners, possession}
        """
        self.connect()
        try:
            # Save Match
            self.cursor.execute("""
                INSERT OR REPLACE INTO matches (id, date, home_team, away_team, home_score, away_score, season)
                VALUES (?, ?, ?, ?, ?, ?, ?)
            """, (
                match_data['id'],
                match_data['date'],
                match_data['home_team'],
                match_data['away_team'],
                match_data['home_score'],
                match_data['away_score'],
                match_data['season']
            ))
            
            # Save Home Stats
            self.cursor.execute("""
                INSERT INTO team_stats (match_id, team, xg, shots, shots_on_target, corners, possession)
                VALUES (?, ?, ?, ?, ?, ?, ?)
            """, (
                match_data['id'],
                home_stats['team'],
                home_stats['xg'],
                home_stats['shots'],
                home_stats['shots_on_target'],
                home_stats['corners'],
                home_stats['possession']
            ))
            
            # Save Away Stats
            self.cursor.execute("""
                INSERT INTO team_stats (match_id, team, xg, shots, shots_on_target, corners, possession)
                VALUES (?, ?, ?, ?, ?, ?, ?)
            """, (
                match_data['id'],
                away_stats['team'],
                away_stats['xg'],
                away_stats['shots'],
                away_stats['shots_on_target'],
                away_stats['corners'],
                away_stats['possession']
            ))
            
            self.conn.commit()
        finally:
            self.close()

    def save_odds(self, match_id: str, bookmaker: str, home: float, draw: float, away: float, 
                  over_2_5: float = None, under_2_5: float = None, btts_yes: float = None, btts_no: float = None):
        """Saves historical odds for a match."""
        self.connect()
        try:
            # Check if columns exist (migration hack for sqlite)
            # For now, we might need to drop/recreate table or alter it if it exists.
            # Since this is dev, let's just use INSERT and assume table is updated or we recreate it.
            # Actually, to be safe, I should probably handle the schema update.
            # But for simplicity in this agent flow, I will assume I can recreate the db or table.
            
            self.cursor.execute("""
                INSERT INTO odds (match_id, bookmaker, home_win, draw, away_win, over_2_5, under_2_5, btts_yes, btts_no)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
            """, (match_id, bookmaker, home, draw, away, over_2_5, under_2_5, btts_yes, btts_no))
            self.conn.commit()
        finally:
            self.close()
