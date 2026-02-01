import requests
from config import config
import json
import os
import urllib.parse

class WhoopClient:
    def __init__(self):
        self.base_url = "https://api.prod.whoop.com/developer"
        self.auth_url = "https://api.prod.whoop.com/oauth/oauth2/auth"
        self.token_url = "https://api.prod.whoop.com/oauth/oauth2/token"
        
        self.token_file = config.WHOOP_TOKEN_FILE
        self.access_token = self._load_token()
        
        # Fallback to config if file empty
        if not self.access_token:
             self.access_token = config.WHOOP_ACCESS_TOKEN
             
        self.headers = {
            "Authorization": f"Bearer {self.access_token}"
        }

    def _load_token(self):
        if os.path.exists(self.token_file):
            try:
                with open(self.token_file, 'r') as f:
                    data = json.load(f)
                    return data.get("access_token")
            except:
                return None
        return None

    def _save_token(self, token_data):
        with open(self.token_file, 'w') as f:
            json.dump(token_data, f)

    def get_authorization_url(self):
        """Generate the URL for the user to login to Whoop"""
        params = {
            "client_id": config.WHOOP_CLIENT_ID,
            "response_type": "code",
            "redirect_uri": config.WHOOP_REDIRECT_URI,
            "scope": "read:profile read:recovery read:cycles read:sleep",
            "state": "whoop_auth_state" 
        }
        return f"{self.auth_url}?{urllib.parse.urlencode(params)}"

    def exchange_token(self, code: str):
        """Exchange auth code for access token"""
        data = {
            "grant_type": "authorization_code",
            "code": code,
            "client_id": config.WHOOP_CLIENT_ID,
            "client_secret": config.WHOOP_CLIENT_SECRET,
            "redirect_uri": config.WHOOP_REDIRECT_URI
        }
        
        try:
            response = requests.post(self.token_url, data=data)
            response.raise_for_status()
            token_data = response.json()
            
            # Update local instance
            self.access_token = token_data.get("access_token")
            self._save_token(token_data)
            
            # Be sure to update connection headers
            self.headers["Authorization"] = f"Bearer {self.access_token}"
            
            return token_data
        except Exception as e:
            print(f"Whoop Token Exchange Error: {e}")
            if hasattr(e, 'response') and e.response:
                print(e.response.text)
            return {"error": str(e)}

    def get_profile(self):
        if not self.access_token:
            return {"error": "No access token provided"}
            
        try:
            response = requests.get(f"{self.base_url}/v2/user/profile/basic", headers=self.headers)
            response.raise_for_status()
            return response.json()
        except Exception as e:
            print(f"Whoop Profile Error: {e}")
            return {}

    def get_cycle_data(self, start_date: str = None, limit: int = 10):
        # Fetch recovery/strain cycles
        if not self.access_token:
            return []

        params = {"limit": limit}
        if start_date:
            params['start'] = start_date
            
        try:
            response = requests.get(f"{self.base_url}/v2/cycle", headers=self.headers, params=params)
            response.raise_for_status()
            data = response.json()
            return data.get("records", [])
        except Exception as e:
            print(f"Whoop Cycle Error: {e}")
            return []

    def get_recovery_data(self, start_date: str = None, limit: int = 1):
        if not self.access_token:
            return []
        
        params = {"limit": limit}
        if start_date:
            params['start'] = start_date

        try:
            response = requests.get(f"{self.base_url}/v2/recovery", headers=self.headers, params=params)
            response.raise_for_status()
            data = response.json()
            return data.get("records", [])
        except Exception as e:
            print(f"Whoop Recovery Error: {e}")
            return []

    def get_sleep_data(self, start_date: str = None, limit: int = 1):
        if not self.access_token:
            return []
        
        params = {"limit": limit}
        if start_date:
            params['start'] = start_date

        try:
            response = requests.get(f"{self.base_url}/v2/activity/sleep", headers=self.headers, params=params)
            response.raise_for_status()
            data = response.json()
            return data.get("records", [])
        except Exception as e:
            print(f"Whoop Sleep Error: {e}")
            return []
