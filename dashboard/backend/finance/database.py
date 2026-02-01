import sqlite3
import os
from datetime import datetime, timedelta
from typing import List, Dict, Optional
from finance.category_mapping import map_transaction_to_budget_category
from config import config

class TransactionDatabase:
    def __init__(self, db_path: str = None):
        if db_path is None:
            db_path = config.DB_PATH
        
        self.db_path = db_path
        self.init_database()
    
    def init_database(self):
        """Initialize database and create tables if they don't exist"""
        conn = sqlite3.connect(self.db_path)
        cursor = conn.cursor()
        
        cursor.execute("""
            CREATE TABLE IF NOT EXISTS transactions (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                transaction_id TEXT UNIQUE NOT NULL,
                account_id TEXT NOT NULL,
                date DATE NOT NULL,
                name TEXT,
                amount REAL NOT NULL,
                category_primary TEXT,
                category_detailed TEXT,
                budget_category TEXT,
                pending BOOLEAN DEFAULT 0,
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            )
        """)
        
        # Create indexes
        cursor.execute("CREATE INDEX IF NOT EXISTS idx_date ON transactions(date)")
        cursor.execute("CREATE INDEX IF NOT EXISTS idx_budget_category ON transactions(budget_category)")
        cursor.execute("CREATE INDEX IF NOT EXISTS idx_account_id ON transactions(account_id)")
        
        conn.commit()
        conn.close()
    
    def insert_transaction(self, transaction: Dict) -> bool:
        """Insert a single transaction, skip if duplicate"""
        try:
            conn = sqlite3.connect(self.db_path)
            cursor = conn.cursor()
            
            # Map to budget category
            budget_category = map_transaction_to_budget_category(transaction)
            
            # Extract personal finance category
            pfc = transaction.get('personal_finance_category', {})
            
            cursor.execute("""
                INSERT OR IGNORE INTO transactions 
                (transaction_id, account_id, date, name, amount, 
                 category_primary, category_detailed, budget_category, pending)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
            """, (
                transaction.get('transaction_id'),
                transaction.get('account_id'),
                transaction.get('date'),
                transaction.get('name'),
                transaction.get('amount'),
                pfc.get('primary'),
                pfc.get('detailed'),
                budget_category,
                transaction.get('pending', False)
            ))
            
            conn.commit()
            inserted = cursor.rowcount > 0
            conn.close()
            return inserted
        except Exception as e:
            print(f"Error inserting transaction: {e}")
            return False
    
    def insert_transactions_bulk(self, transactions: List[Dict]) -> int:
        """Insert multiple transactions, return count of new transactions"""
        inserted_count = 0
        for tx in transactions:
            if self.insert_transaction(tx):
                inserted_count += 1
        return inserted_count
    
    def get_transactions(self, start_date: str = None, end_date: str = None, 
                        budget_category: str = None) -> List[Dict]:
        """Get transactions with optional filters"""
        conn = sqlite3.connect(self.db_path)
        conn.row_factory = sqlite3.Row
        cursor = conn.cursor()
        
        query = "SELECT * FROM transactions WHERE 1=1"
        params = []
        
        if start_date:
            query += " AND date >= ?"
            params.append(start_date)
        
        if end_date:
            query += " AND date <= ?"
            params.append(end_date)
        
        if budget_category:
            query += " AND budget_category = ?"
            params.append(budget_category)
        
        query += " ORDER BY date DESC"
        
        cursor.execute(query, params)
        rows = cursor.fetchall()
        
        transactions = [dict(row) for row in rows]
        conn.close()
        return transactions
    
    def get_monthly_spending(self, year: int, month: int) -> Dict:
        """Get spending aggregated by budget category for a specific month (Outflows only)"""
        start_date = f"{year}-{month:02d}-01"
        
        # Calculate last day of month
        if month == 12:
            end_date = f"{year}-12-31"
        else:
            next_month = datetime(year, month + 1, 1)
            last_day = (next_month - timedelta(days=1)).day
            end_date = f"{year}-{month:02d}-{last_day:02d}"
        
        conn = sqlite3.connect(self.db_path)
        cursor = conn.cursor()
        
        cursor.execute("""
            SELECT budget_category, SUM(amount) as total
            FROM transactions
            WHERE date >= ? AND date <= ? AND pending = 0 AND amount > 0
            GROUP BY budget_category
            ORDER BY total DESC
        """, (start_date, end_date))
        
        results = {}
        for row in cursor.fetchall():
            results[row[0]] = row[1]
        
        conn.close()
        return results
    
    def get_yearly_spending(self, year: int) -> Dict:
        """Get spending aggregated by month for a specific year (Outflows only)"""
        conn = sqlite3.connect(self.db_path)
        cursor = conn.cursor()
        
        cursor.execute("""
            SELECT strftime('%m', date) as month, SUM(amount) as total
            FROM transactions
            WHERE strftime('%Y', date) = ? AND pending = 0 AND amount > 0
            GROUP BY month
            ORDER BY month
        """, (str(year),))
        
        results = {}
        for row in cursor.fetchall():
            month_num = int(row[0])
            results[month_num] = row[1]
        
        conn.close()
        return results
    
    def get_last_sync_date(self) -> Optional[str]:
        """Get the date of the most recent transaction in the database"""
        conn = sqlite3.connect(self.db_path)
        cursor = conn.cursor()
        
        cursor.execute("SELECT MAX(date) FROM transactions")
        result = cursor.fetchone()
        
        conn.close()
        return result[0] if result and result[0] else None
    
    def get_transaction_count(self) -> int:
        """Get total number of transactions in database"""
        conn = sqlite3.connect(self.db_path)
        cursor = conn.cursor()
        
        cursor.execute("SELECT COUNT(*) FROM transactions")
        count = cursor.fetchone()[0]
        
        conn.close()
        return count
    def get_daily_spending_total(self, date_str: str) -> float:
        """Get total spending for a specific day (Outflows only)"""
        conn = sqlite3.connect(self.db_path)
        cursor = conn.cursor()
        
        cursor.execute("""
            SELECT SUM(amount)
            FROM transactions
            WHERE date = ? AND pending = 0 AND amount > 0
        """, (date_str,))
        
        result = cursor.fetchone()
        conn.close()
        
        return result[0] if result and result[0] else 0.0
