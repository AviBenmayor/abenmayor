import json
import os
from datetime import datetime
from typing import Dict, List, Optional
import pandas as pd

class BudgetManager:
    def __init__(self):
        self.budget_file = os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "budget.json")
        self.budget_data = self._load_budget()
        
        # Auto-load Budget.csv if it exists and budget.json is empty
        if not self.budget_data.get("categories"):
            self._auto_load_budget_csv()
    
    def _auto_load_budget_csv(self):
        """Auto-load Budget.csv from dashboard directory"""
        # Look for Budget.csv in the dashboard directory
        backend_dir = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
        budget_csv_path = os.path.join(os.path.dirname(backend_dir), "Budget.csv")
        
        if os.path.exists(budget_csv_path):
            print(f"Auto-loading budget from {budget_csv_path}")
            categories = self.parse_csv(budget_csv_path)
            if categories:
                self.update_budget(categories)
                print(f"Loaded {len(categories)} budget categories")
        else:
            print(f"Budget.csv not found at {budget_csv_path}")
    
    def _load_budget(self) -> Dict:
        """Load budget from JSON file"""
        if os.path.exists(self.budget_file):
            try:
                with open(self.budget_file, 'r') as f:
                    return json.load(f)
            except:
                return {"categories": {}, "last_updated": None}
        return {"categories": {}, "last_updated": None}
    
    def _save_budget(self):
        """Save budget to JSON file"""
        with open(self.budget_file, 'w') as f:
            json.dump(self.budget_data, f, indent=2)
    
    def parse_excel(self, file_path: str) -> Dict:
        """Parse budget from Excel file
        
        Expected format:
        - Column A: Category name
        - Column B: Monthly budget amount
        """
        try:
            df = pd.read_excel(file_path)
            
            # Try to find category and amount columns
            # Look for common column names
            category_col = None
            amount_col = None
            
            for col in df.columns:
                col_lower = str(col).lower()
                if 'category' in col_lower or 'name' in col_lower:
                    category_col = col
                elif 'budget' in col_lower or 'amount' in col_lower or 'monthly' in col_lower:
                    amount_col = col
            
            # If not found, use first two columns
            if category_col is None:
                category_col = df.columns[0]
            if amount_col is None and len(df.columns) > 1:
                amount_col = df.columns[1]
            
            categories = {}
            for _, row in df.iterrows():
                category = str(row[category_col]).strip()
                try:
                    amount = float(row[amount_col])
                    if category and amount > 0:
                        categories[category] = amount
                except (ValueError, TypeError):
                    continue
            
            return categories
        except Exception as e:
            print(f"Error parsing Excel: {e}")
            return {}
    
    def parse_csv(self, file_path: str) -> Dict:
        """Parse budget from CSV file in standardized format
        
        Expected format:
        - Row 1: Empty or header labels
        - Row 2: Column headers (Category, Budget, Actual, Difference)
        - Subsequent rows: Category name and budget amount (with $ and commas)
        """
        try:
            # Read CSV, skipping first row if it's empty
            df = pd.read_csv(file_path)
            
            # Check if first row is the header row (contains "Category")
            if 'Category' not in df.columns:
                # First row might be empty, try reading with skiprows
                df = pd.read_csv(file_path, skiprows=1)
            
            # Find the Category and Budget columns
            category_col = None
            budget_col = None
            
            for col in df.columns:
                col_str = str(col).strip()
                if col_str == 'Category' or 'category' in col_str.lower():
                    category_col = col
                elif col_str == 'Budget' or 'budget' in col_str.lower():
                    budget_col = col
            
            if not category_col or not budget_col:
                print(f"Could not find Category or Budget columns. Columns: {df.columns.tolist()}")
                return {}
            
            categories = {}
            for _, row in df.iterrows():
                category = str(row[category_col]).strip()
                budget_str = str(row[budget_col]).strip()
                
                # Skip if category is empty, NaN, or "Total"
                if not category or category == 'nan' or category.lower() == 'total':
                    continue
                
                try:
                    # Remove $ and commas, then convert to float
                    amount = float(budget_str.replace('$', '').replace(',', ''))
                    if amount > 0:
                        categories[category] = amount
                except (ValueError, TypeError, AttributeError):
                    continue
            
            return categories
        except Exception as e:
            print(f"Error parsing CSV: {e}")
            import traceback
            traceback.print_exc()
            return {}
    
    def update_budget(self, categories: Dict[str, float]):
        """Update budget categories"""
        self.budget_data["categories"] = categories
        self.budget_data["last_updated"] = datetime.now().isoformat()
        self._save_budget()
    
    def get_budget(self) -> Dict:
        """Get current budget"""
        return self.budget_data
    
    def compare_to_spending(self, transactions: List[Dict]) -> Dict:
        """Compare budget to actual spending
        
        Args:
            transactions: List of transaction dicts with Plaid category fields
        
        Returns:
            Dict with budget vs actual for each category
        """
        from finance.category_mapping import map_transaction_to_budget_category
        
        spending_by_category = {}
        
        # Aggregate spending by budget category
        for tx in transactions:
            # Map Plaid category to budget category
            budget_category = map_transaction_to_budget_category(tx)
            amount = abs(float(tx.get('amount', 0)))
            
            if budget_category not in spending_by_category:
                spending_by_category[budget_category] = 0
            spending_by_category[budget_category] += amount
        
        # Compare to budget
        comparison = {}
        for category, budgeted in self.budget_data.get("categories", {}).items():
            actual = spending_by_category.get(category, 0)
            comparison[category] = {
                "budgeted": budgeted,
                "actual": actual,
                "remaining": budgeted - actual,
                "percent_used": (actual / budgeted * 100) if budgeted > 0 else 0
            }
        
        # Add categories with spending but no budget
        for category, actual in spending_by_category.items():
            if category not in comparison:
                comparison[category] = {
                    "budgeted": 0,
                    "actual": actual,
                    "remaining": -actual,
                    "percent_used": 0
                }
        
        return comparison
    
    def get_daily_tracking(self, transactions: List[Dict]) -> Dict:
        """Get yesterday's spending compared to daily budget allowance
        
        Args:
            transactions: All transactions from the current month
        
        Returns:
            Dict with yesterday's spending vs daily budget for each category
        """
        from datetime import datetime, timedelta, date
        from finance.category_mapping import map_transaction_to_budget_category
        
        # Get yesterday's date
        yesterday = (datetime.now() - timedelta(days=1)).date()
        
        # Filter transactions from yesterday
        yesterday_transactions = [
            tx for tx in transactions
            if datetime.strptime(tx.get('date', ''), '%Y-%m-%d').date() == yesterday
        ]
        
        # Calculate spending by category for yesterday
        yesterday_spending = {}
        for tx in yesterday_transactions:
            budget_category = map_transaction_to_budget_category(tx)
            amount = abs(float(tx.get('amount', 0)))
            
            if budget_category not in yesterday_spending:
                yesterday_spending[budget_category] = 0
            yesterday_spending[budget_category] += amount
        
        # Calculate daily budget (monthly budget / days in month)
        today = date.today()
        days_in_month = (date(today.year, today.month + 1, 1) - timedelta(days=1)).day if today.month < 12 else 31
        
        daily_tracking = {}
        for category, monthly_budget in self.budget_data.get("categories", {}).items():
            daily_budget = monthly_budget / days_in_month
            actual = yesterday_spending.get(category, 0)
            
            daily_tracking[category] = {
                "daily_budget": daily_budget,
                "yesterday_spent": actual,
                "difference": daily_budget - actual,
                "status": "under" if actual <= daily_budget else "over"
            }
        
        # Add summary
        total_daily_budget = sum(item["daily_budget"] for item in daily_tracking.values())
        total_yesterday_spent = sum(item["yesterday_spent"] for item in daily_tracking.values())
        
        return {
            "date": str(yesterday),
            "categories": daily_tracking,
            "summary": {
                "total_daily_budget": total_daily_budget,
                "total_yesterday_spent": total_yesterday_spent,
                "difference": total_daily_budget - total_yesterday_spent,
                "status": "under" if total_yesterday_spent <= total_daily_budget else "over"
            }
        }
