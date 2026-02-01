import os
from dotenv import load_dotenv

load_dotenv()

class Config:
    def __init__(self):
        self.PLAID_CLIENT_ID = os.getenv("PLAID_CLIENT_ID", "")
        self.PLAID_ENV = os.getenv("PLAID_ENV", "sandbox")
        
        # Select secret based on environment
        if self.PLAID_ENV == "production":
            self.PLAID_SECRET = os.getenv("PLAID_PRODUCTION_SECRET", "")
        elif self.PLAID_ENV == "development":
            self.PLAID_SECRET = os.getenv("PLAID_DEVELOPMENT_SECRET") or os.getenv("PLAID_PRODUCTION_SECRET", "")
        else:
            self.PLAID_SECRET = os.getenv("PLAID_SANDBOX_SECRET", "")

        self.PLAID_REDIRECT_URI = os.getenv("PLAID_REDIRECT_URI", "http://localhost:3000")
        
        self.WHOOP_ACCESS_TOKEN = os.getenv("WHOOP_ACCESS_TOKEN", "")
        self.WHOOP_CLIENT_ID = os.getenv("WHOOP_CLIENT_ID", "")
        self.WHOOP_CLIENT_SECRET = os.getenv("WHOOP_CLIENT_SECRET", "")
        self.WHOOP_REDIRECT_URI = os.getenv("WHOOP_REDIRECT_URI", "http://localhost:8000/callback")
        
        self.FIDELITY_USERNAME = os.getenv("FIDELITY_USERNAME", "")
        self.FIDELITY_PASSWORD = os.getenv("FIDELITY_PASSWORD", "")

        # Storage paths
        backend_dir = os.path.dirname(os.path.abspath(__file__))
        env_suffix = f"_{self.PLAID_ENV}"
        
        self.DB_PATH = os.path.join(backend_dir, f"transactions{env_suffix}.db")
        self.PLAID_TOKEN_FILE = os.path.join(backend_dir, f"plaid_tokens{env_suffix}.json")
        self.BALANCE_HISTORY_FILE = os.path.join(backend_dir, f"balance_history{env_suffix}.json")
        self.WHOOP_TOKEN_FILE = os.path.join(backend_dir, f"whoop_token{env_suffix}.json")

config = Config()
