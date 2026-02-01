import plaid
from plaid.api import plaid_api
from plaid.model.transactions_get_request import TransactionsGetRequest
from plaid.model.transactions_get_request_options import TransactionsGetRequestOptions
from plaid.model.accounts_get_request import AccountsGetRequest
from datetime import datetime, timedelta
from config import config
from finance.database import TransactionDatabase

class BankingClient:
    def __init__(self):
        # Handle environment selection manually if SDK is missing Development
        if config.PLAID_ENV == 'sandbox':
            host = plaid.Environment.Sandbox
        elif config.PLAID_ENV == 'development':
            host = "https://development.plaid.com"
        else:
            host = plaid.Environment.Production

        configuration = plaid.Configuration(
            host=host,
            api_key={
                'clientId': config.PLAID_CLIENT_ID,
                'secret': config.PLAID_SECRET,
            }
        )
        api_client = plaid.ApiClient(configuration)
        self.client = plaid_api.PlaidApi(api_client)
        
        self.token_file = config.PLAID_TOKEN_FILE
        self.access_tokens = self._load_tokens()
        
        # Initialize database
        self.db = TransactionDatabase()

    def _load_tokens(self):
        import json
        import os
        if os.path.exists(self.token_file):
            try:
                with open(self.token_file, 'r') as f:
                    return json.load(f)
            except:
                return []
        return []

    def _save_token(self, token: str):
        import json
        if token not in self.access_tokens:
            self.access_tokens.append(token)
            with open(self.token_file, 'w') as f:
                json.dump(self.access_tokens, f)

    def create_link_token(self, user_id: str):
        from plaid.model.link_token_create_request import LinkTokenCreateRequest
        from plaid.model.link_token_create_request_user import LinkTokenCreateRequestUser
        from plaid.model.products import Products
        from plaid.model.country_code import CountryCode

        # Products to request - Transactions mostly
        products = [Products('transactions')]
        
        request = LinkTokenCreateRequest(
            products=products,
            client_name="Personal Dashboard",
            country_codes=[CountryCode('US')],
            language='en',
            user=LinkTokenCreateRequestUser(
                client_user_id=user_id
            )
        )
        print(f"DEBUG: Plaid Request: {request}")
        response = self.client.link_token_create(request)
        print(f"DEBUG: Plaid Response: {response}")
        return response['link_token']

    def exchange_public_token(self, public_token: str):
        from plaid.model.item_public_token_exchange_request import ItemPublicTokenExchangeRequest
        
        request = ItemPublicTokenExchangeRequest(
            public_token=public_token
        )
        response = self.client.item_public_token_exchange(request)
        access_token = response['access_token']
        self._save_token(access_token)
        return {"access_token": access_token}

    def add_access_token(self, token: str):
        self._save_token(token)

    def get_balances(self):
        all_accounts = []
        for access_token in self.access_tokens:
            try:
                request = AccountsGetRequest(access_token=access_token)
                response = self.client.accounts_get(request)
                # Convert response to dict
                response_dict = response.to_dict()
                all_accounts.extend(response_dict.get('accounts', []))
            except Exception as e:
                print(f"Error fetching balances: {e}")
        
        # Save balance snapshot
        self._save_balance_snapshot(all_accounts)
        return all_accounts
    
    def _save_balance_snapshot(self, accounts: list):
        """Save daily balance snapshot for net worth tracking"""
        import json
        from datetime import date
        import os
        
        history_file = config.BALANCE_HISTORY_FILE
        
        # Load existing history
        history = []
        if os.path.exists(history_file):
            try:
                with open(history_file, 'r') as f:
                    history = json.load(f)
            except:
                history = []
        
        # Calculate total net worth
        total_balance = sum(
            acc.get('balances', {}).get('current', 0) or 0 
            for acc in accounts
        )
        
        today = str(date.today())
        
        # Check if we already have a snapshot for today
        existing_index = next((i for i, h in enumerate(history) if h['date'] == today), None)
        
        snapshot = {
            "date": today,
            "net_worth": total_balance,
            "accounts": len(accounts)
        }
        
        if existing_index is not None:
            history[existing_index] = snapshot
        else:
            history.append(snapshot)
        
        # Keep only last 90 days
        history = sorted(history, key=lambda x: x['date'])[-90:]
        
        with open(history_file, 'w') as f:
            json.dump(history, f, indent=2)
    
    def get_net_worth_history(self):
        """Get historical net worth data"""
        import json
        import os
        
        history_file = config.BALANCE_HISTORY_FILE
        
        if os.path.exists(history_file):
            try:
                with open(history_file, 'r') as f:
                    return json.load(f)
            except:
                return []
        return []

    def get_transactions(self, days: int = 30):
        # Convert to date and then to isoformat string, as Plaid SDK expects strings
        start_date = (datetime.now() - timedelta(days=days)).date().isoformat()
        end_date = datetime.now().date().isoformat()
        
        all_transactions = []
        for access_token in self.access_tokens:
            try:
                options = TransactionsGetRequestOptions(count=500)
                request = TransactionsGetRequest(
                    access_token=access_token,
                    start_date=start_date,
                    end_date=end_date,
                    options=options
                )
                response = self.client.transactions_get(request)
                # Convert Plaid response object to dict
                response_dict = response.to_dict()
                all_transactions.extend(response_dict.get('transactions', []))
            except Exception as e:
                print(f"Error fetching transactions: {e}")
                import traceback
                traceback.print_exc()
        return all_transactions
    
    def sync_transactions(self, days: int = None) -> dict:
        """Sync transactions from Plaid to database
        
        Args:
            days: Number of days to fetch. If None, fetches based on last sync:
                  - First sync: 730 days (2 years)
                  - Subsequent syncs: 30 days
        
        Returns:
            Dict with sync statistics
        """
        # Determine date range
        if days is None:
            last_sync = self.db.get_last_sync_date()
            if last_sync is None:
                # First sync - get 2 years of data
                days = 730
                print("First sync: Fetching 2 years of transaction history...")
            else:
                # Incremental sync - get last 30 days
                days = 30
                print(f"Incremental sync: Fetching last 30 days since {last_sync}...")
        
        # Fetch transactions from Plaid
        transactions = self.get_transactions(days=days)
        
        # Insert into database
        inserted_count = self.db.insert_transactions_bulk(transactions)
        
        return {
            "success": True,
            "fetched": len(transactions),
            "inserted": inserted_count,
            "duplicates": len(transactions) - inserted_count,
            "total_in_db": self.db.get_transaction_count()
        }
    
    def get_transactions_from_db(self, start_date: str = None, end_date: str = None) -> list:
        """Get transactions from database instead of Plaid API"""
        return self.db.get_transactions(start_date=start_date, end_date=end_date)
